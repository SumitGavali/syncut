"""
app.py — Web backend for SyncCut.

Drives the upgraded pipeline (Phases 1–6):
    config.py, extract.py, robustness.py, confidence.py,
    sync_engine.py, drift.py, rough_cut.py,
    timeline_builder.py, export_switch_timeline.py

Supports new API routes for:
  - Global multi-source sync (--sync-mode global / reference)
  - Drift correction
  - Rough cut export (FCPXML via rough_cut.py)
  - Confidence report download (CSV)

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000
"""
import csv
import io
import json
import os
import threading
import time
import traceback
import uuid
import webbrowser

from flask import Flask, request, jsonify, send_file, render_template
import job_manager, db
# from synccut import job_manager, db
from flask_cors import CORS   
from werkzeug.utils import secure_filename

from confidence import badge_and_status_from_confidence
from config import DEFAULT_SYNC_MODE, DEFAULT_DRIFT_WINDOW_SEC, DRIFT_CORRECT_THRESHOLD_MS_PER_HR
from drift import windowed_offsets, analyze_drift, correct_audio_drift_resample
from extract import extract_audio, extract_audio_batch
from robustness import preflight_media_check, check_sample_rates
from rough_cut import generate_active_speaker_roughcut, export_roughcut_fcpxml
from fcp7_exporter import export_fcp7_xml
from sync_engine import load_wav, solve_multi_source_sync
from timeline_builder import build_timeline, export_timeline
from export_switch_timeline import build_switch_timeline
from paths import (
    get_base_dir,
    get_user_data_dir,
    get_sessions_dir,
    get_audio_cache_dir,
    cleanup_old_temp_files,
)

APP_ROOT = str(get_base_dir())
UPLOAD_ROOT = str(get_sessions_dir())
cleanup_old_temp_files(max_age_hours=24.0)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": [
    "https://snycut-site-ten.vercel.app",
    "http://localhost:3000"  # keep for local dev
]}})
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB

# In-memory session store — keyed per browser session
SESSIONS = {}


def session_dir(session_id):
    d = os.path.join(UPLOAD_ROOT, session_id)
    os.makedirs(d, exist_ok=True)
    return d


def get_session(session_id):
    """Retrieve session or initialize gracefully if server restarted."""
    if not session_id:
        return None
    if session_id not in SESSIONS:
        sdir = session_dir(session_id)
        report_path = os.path.join(sdir, "sync_report.json")
        report_results = []
        if os.path.exists(report_path):
            try:
                with open(report_path) as f:
                    report_results = json.load(f)
            except Exception:
                pass

        SESSIONS[session_id] = {
            "reference_path": None,
            "input_paths": [],
            "all_signals": [],
            "fs": 16000,
            "report_results": report_results,
            "report_json_path": report_path if os.path.exists(report_path) else None,
            "media_dir": sdir,
            "last_switches": None,
            "last_switches_media_dir": sdir,
        }
    return SESSIONS[session_id]


# ─────────────────────────────── Pages ──────────────────────────────────────

@app.route("/")
def landing():
    return render_template("index.html")


@app.route("/app")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/waitlist", methods=["POST"])
def waitlist_signup():
    """Handle early access / beta waitlist signup requests."""
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        email = data.get("email", "").strip()
        nle = data.get("nle", "").strip()
        cameras = data.get("cameras", "").strip()
        # Log signup to a local file or standard output for beta tracking
        log_dir = os.path.join(APP_ROOT, "uploads")
        os.makedirs(log_dir, exist_ok=True)
        waitlist_file = os.path.join(log_dir, "waitlist.jsonl")
        with open(waitlist_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"email": email, "nle": nle, "cameras": cameras}) + "\n")
        return jsonify({"status": "ok", "message": "Successfully added to beta waitlist."})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ────────────────────────────── Session API ───────────────────────────────────

@app.route("/api/session", methods=["POST"])
def new_session():
    session_id = uuid.uuid4().hex[:12]
    get_session(session_id)
    return jsonify({"session_id": session_id})


# ────────────────────────────── Sync API ──────────────────────────────────────

@app.route("/api/sync", methods=["POST"])
def run_sync():
    """
    Global multi-source sync.
    Accepts: reference file, N input files, sync_mode, drift_correct flag.
    Returns: sync report JSON with calibrated confidence badges and drift info.
    """
    session_id = request.form.get("session_id")
    state = get_session(session_id)
    if not state:
        return jsonify({"error": "Invalid or missing session_id"}), 400

    sdir = session_dir(session_id)

    reference_file = request.files.get("reference")
    input_files = request.files.getlist("inputs")
    if not reference_file or not input_files:
        return jsonify({"error": "A reference file and at least one source file are required."}), 400

    sync_mode = request.form.get("sync_mode", DEFAULT_SYNC_MODE)
    drift_correct = request.form.get("drift_correct", "false").lower() == "true"
    drift_window = float(request.form.get("drift_window", DEFAULT_DRIFT_WINDOW_SEC))

    # Optional metadata sent from browser Web Audio extractor
    meta_raw = request.form.get("metadata")
    client_meta = {}
    if meta_raw:
        try:
            client_meta = json.loads(meta_raw)
        except Exception:
            client_meta = {}

    ref_orig_name = client_meta.get("reference_name") or reference_file.filename
    ref_filename = secure_filename(reference_file.filename)
    ref_path = os.path.join(sdir, ref_filename)
    reference_file.save(ref_path)
    state["reference_path"] = ref_path

    input_paths = []
    input_orig_names = client_meta.get("input_names", [])
    for idx, f in enumerate(input_files):
        fname = secure_filename(f.filename)
        fpath = os.path.join(sdir, fname)
        f.save(fpath)
        input_paths.append(fpath)
    state["input_paths"] = input_paths
    state["media_dir"] = sdir

    try:
        all_to_extract = [ref_path] + input_paths
        extracted_wavs = []
        for p in all_to_extract:
            # If client uploaded audio wav directly, reuse without ffmpeg extraction
            if p.lower().endswith(".wav"):
                extracted_wavs.append(p)
            else:
                extracted_wavs.append(extract_audio(p, output_dir=os.path.join(sdir, "_audio")))

        ref_wav = extracted_wavs[0]
        sr_ref, ref_sig = load_wav(ref_wav)

        all_signals = [ref_sig]
        all_labels = ["Reference"]
        all_files = [os.path.basename(ref_orig_name)]
        all_paths = [ref_path]

        robustness_flags = {}
        for i, src_path in enumerate(input_paths, start=1):
            label = f"Camera {chr(64 + i)}" if i <= 26 else f"Source {i}"
            src_wav = extracted_wavs[i]
            sr_src, src_sig = load_wav(src_wav)

            # Pre-flight checks
            sr_ok, sr_msg = check_sample_rates(sr_ref, sr_src)
            valid, flags = preflight_media_check(src_path, src_sig, sr_src)
            if flags:
                robustness_flags[label] = flags

            orig_input_name = input_orig_names[i - 1] if (i - 1) < len(input_orig_names) else os.path.basename(src_path)
            all_signals.append(src_sig)
            all_labels.append(label)
            all_files.append(os.path.basename(orig_input_name))
            all_paths.append(src_path)

        # Store signals for downstream use (rough cut, etc.)
        state["all_signals"] = all_signals
        state["fs"] = sr_ref

        # Run global (or reference) sync solver
        offsets, confidences, feature_dicts = solve_multi_source_sync(
            all_signals, sr_ref,
            sync_mode=sync_mode,
            ref_index=0
        )

        results = []
        for idx in range(len(all_signals)):
            label = all_labels[idx]
            fname = all_files[idx]
            offset = float(offsets[idx])
            conf = float(confidences[idx])

            if idx == 0:
                drift_info = {
                    "drift_ms_per_hour": 0.0,
                    "is_significant": False,
                    "reliable_windows": "-",
                    "total_windows": "-",
                    "drift_ci_lower_ms_per_hour": 0.0,
                    "drift_ci_upper_ms_per_hour": 0.0,
                }
                badge, status = "green", "Good (reference)"
            else:
                windows = windowed_offsets(ref_sig, all_signals[idx], sr_ref, window_sec=drift_window)
                drift_info = analyze_drift(windows)
                badge, status = badge_and_status_from_confidence(conf, drift_info["drift_ms_per_hour"])

                if drift_correct and drift_info.get("is_significant", False):
                    slope = drift_info["slope_sec_per_sec"]
                    all_signals[idx] = correct_audio_drift_resample(all_signals[idx], sr_ref, slope)
                    status += " [Drift Resampled]"

            flags_for_label = robustness_flags.get(label, [])
            results.append({
                "source": label,
                "file": fname,
                "offset_sec": round(offset, 3),
                "confidence": round(conf, 3),
                "drift_ms_per_hour": drift_info["drift_ms_per_hour"],
                "drift_ci_lower": drift_info.get("drift_ci_lower_ms_per_hour", 0.0),
                "drift_ci_upper": drift_info.get("drift_ci_upper_ms_per_hour", 0.0),
                "reliable_windows": f"{drift_info.get('reliable_windows', '-')}/{drift_info.get('total_windows', '-')}",
                "badge": badge,
                "status": status,
                "robustness_flags": flags_for_label,
            })

        state["report_results"] = results
        report_path = os.path.join(sdir, "sync_report.json")
        with open(report_path, "w") as f:
            json.dump(results, f, indent=2)
        state["report_json_path"] = report_path

        return jsonify({"results": results})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ────────────────────────── Report Download APIs ──────────────────────────────

@app.route("/api/report/download", methods=["GET"])
def download_report_json():
    session_id = request.args.get("session_id")
    state = SESSIONS.get(session_id)
    if not state or not state.get("report_json_path"):
        return jsonify({"error": "No report available for this session."}), 400
    return send_file(state["report_json_path"], as_attachment=True, download_name="sync_report.json")

# ---------------------------------------------------
# New endpoint: Pre‑flight diagnostics for uploaded media
# ---------------------------------------------------
@app.route("/api/preflight", methods=["POST"]) 
def preflight_diagnostics():
    """Run robustness checks on each uploaded file and return a JSON report.
    Expects the same multipart form as /api/sync (reference + inputs).
    """
    # Grab files without performing sync logic
    reference_file = request.files.get("reference")
    input_files = request.files.getlist("inputs")
    if not reference_file:
        return jsonify({"error": "Reference file required for diagnostics."}), 400
    files = [("reference", reference_file)] + [(f"input_{i}", f) for i, f in enumerate(input_files)]
    results = []
    for label, f in files:
        fname = secure_filename(f.filename)
        temp_path = os.path.join(get_sessions_dir(), "tmp_diag", fname)
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        f.save(temp_path)
        # Load wav if possible for deeper analysis
        try:
            sr, sig = load_wav(temp_path)
        except Exception:
            sr, sig = None, None
        ok, flags = preflight_media_check(temp_path, sig, sr)
        results.append({"label": label, "file": fname, "valid": ok, "flags": flags})
        os.remove(temp_path)
    return jsonify({"diagnostics": results})

# ---------------------------------------------------
# New endpoint: Review / manual offset adjustment
# ---------------------------------------------------
@app.route("/api/review", methods=["POST"]) 
def review_offsets():
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    adjustments = data.get("adjustments", {})  # {"Camera 1": offset_sec, ...}
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"error": "Invalid session_id"}), 400
    # Apply adjustments to stored results
    for r in state.get("report_results", []):
        label = r.get("source")
        if label in adjustments:
            r["offset_sec"] = float(adjustments[label])
            r["status"] = "Manually adjusted"
    # Persist updated report
    report_path = state.get("report_json_path")
    if report_path:
        with open(report_path, "w") as f:
            json.dump(state["report_results"], f, indent=2)
    return jsonify({"status": "adjustments applied", "results": state["report_results"]})

# ---------------------------------------------------
# New endpoint: Async sync job submission
# ---------------------------------------------------
@app.route("/api/sync_async", methods=["POST"]) 
def run_sync_async():
    # Accept same payload as /api/sync but execute in background
    session_id = request.form.get("session_id")
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400
    # Store raw request data for background processing
    payload = request.form.to_dict(flat=False)
    files = request.files
    job_id = job_manager.submit_job(session_id, payload, files)
    return jsonify({"job_id": job_id})

# ---------------------------------------------------
# New endpoint: Job status query
# ---------------------------------------------------
@app.route("/api/job/status", methods=["GET"]) 
def job_status():
    job_id = request.args.get("job_id")
    status = job_manager.get_status(job_id)
    if status is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(status)



@app.route("/api/report/csv", methods=["GET"])
def download_report_csv():
    """Download sync confidence report as CSV."""
    session_id = request.args.get("session_id")
    state = SESSIONS.get(session_id)
    if not state or not state.get("report_results"):
        return jsonify({"error": "No report available. Run sync first."}), 400

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Source", "File", "Offset_Sec", "Drift_MS_Per_HR",
        "Drift_CI_Lower", "Drift_CI_Upper",
        "Confidence", "Badge", "Status", "Robustness_Flags"
    ])
    for r in state["report_results"]:
        writer.writerow([
            r["source"], r["file"], r["offset_sec"],
            r["drift_ms_per_hour"], r.get("drift_ci_lower", ""),
            r.get("drift_ci_upper", ""),
            r["confidence"], r["badge"], r["status"],
            "; ".join(r.get("robustness_flags", []))
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        as_attachment=True,
        download_name="sync_confidence_report.csv",
        mimetype="text/csv",
    )


# ─────────────────────────── Timeline Export APIs ─────────────────────────────

@app.route("/api/export/timeline", methods=["POST"])
def export_timeline_route():
    """Export offset-aligned timeline (FCPXML or FCP7 XML / xmeml)."""
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    fps = float(data.get("fps", 25))
    export_format = data.get("format", "fcpxml").lower()
    state = SESSIONS.get(session_id)
    if not state or not state.get("report_json_path"):
        return jsonify({"error": "Run sync analysis first."}), 400

    sdir = session_dir(session_id)
    try:
        if export_format in ("fcp7", "xmeml", "xml"):
            out_path = os.path.join(sdir, "timeline_premiere.xml")
            export_fcp7_xml(state["report_json_path"], state["media_dir"], out_path, fps=fps)
            return send_file(out_path, as_attachment=True, download_name="timeline_premiere.xml")
        else:
            out_path = os.path.join(sdir, "timeline.fcpxml")
            tl = build_timeline(state["report_json_path"], state["media_dir"], fps=fps)
            export_timeline(tl, out_path)
            return send_file(out_path, as_attachment=True, download_name="timeline.fcpxml")
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/switches", methods=["POST"])
def analyze_switches_route():
    """Generate camera switch rough cut using new rough_cut.py ASD pipeline."""
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    state = SESSIONS.get(session_id)
    if not state or not state.get("report_json_path"):
        return jsonify({"error": "Run sync analysis first."}), 400

    try:
        results = state["report_results"]
        all_signals = state.get("all_signals", [])
        fs = state.get("fs", 16000)

        if not all_signals:
            return jsonify({"error": "No audio signals cached. Please re-run sync."}), 400

        # Build sources_data dict for rough_cut
        sources_data = {}
        for i, r in enumerate(results):
            if i < len(all_signals):
                sources_data[r["source"]] = {
                    "signal": all_signals[i],
                    "offset_sec": r["offset_sec"],
                    "file": r["file"],
                }

        segments = generate_active_speaker_roughcut(sources_data, fs=fs)
        if not segments:
            return jsonify({"segments": [], "message": "No camera switches detected."})

        state["last_switches"] = segments
        state["last_switches_media_dir"] = state["media_dir"]

        sdir = session_dir(session_id)
        switches_path = os.path.join(sdir, "camera_switches.json")
        with open(switches_path, "w") as f:
            json.dump(segments, f, indent=2)

        return jsonify({"segments": segments})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/switch-timeline", methods=["POST"])
def export_switch_timeline_route():
    """Export rough cut FCPXML using new rough_cut.py exporter."""
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    fps = float(data.get("fps", 25))
    state = SESSIONS.get(session_id)
    if not state or not state.get("last_switches"):
        return jsonify({"error": "Run 'Suggest Camera Switches' first."}), 400

    sdir = session_dir(session_id)
    out_path = os.path.join(sdir, "rough_cut.fcpxml")
    try:
        export_roughcut_fcpxml(state["last_switches"], output_path=out_path, fps=fps)
        return send_file(out_path, as_attachment=True, download_name="rough_cut.fcpxml")
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def find_free_port(preferred: int = 5000) -> int:
    """Find a free port starting from preferred, or let OS pick one."""
    import socket
    # Try preferred first
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass

    # Ask OS for an ephemeral free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    # Initialize SQLite DB for session tracking
    db.init_db()
    # Start background job executor
    job_manager.start_executor()

    host = "127.0.0.1"
    port = find_free_port(5000)
    url = f"http://{host}:{port}/app"
    # Open browser automatically
    threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)), daemon=True).start()
    print(f"SyncCut Desktop running at {url}")
    app.run(host=host, port=port, debug=False)



