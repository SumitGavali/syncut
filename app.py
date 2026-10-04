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
import traceback
import uuid

from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename

from confidence import badge_and_status_from_confidence
from config import DEFAULT_SYNC_MODE, DEFAULT_DRIFT_WINDOW_SEC, DRIFT_CORRECT_THRESHOLD_MS_PER_HR
from drift import windowed_offsets, analyze_drift, correct_audio_drift_resample
from extract import extract_audio
from robustness import preflight_media_check, check_sample_rates
from rough_cut import generate_active_speaker_roughcut, export_roughcut_fcpxml
from sync_engine import load_wav, solve_multi_source_sync
from timeline_builder import build_timeline, export_timeline
from export_switch_timeline import build_switch_timeline

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
UPLOAD_ROOT = os.path.join(APP_ROOT, "uploads")
os.makedirs(UPLOAD_ROOT, exist_ok=True)

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


# ─────────────────────────────── Pages ──────────────────────────────────────

@app.route("/")
def landing():
    return render_template("index.html")


@app.route("/app")
def dashboard():
    return render_template("dashboard.html")


# ────────────────────────────── Session API ───────────────────────────────────

@app.route("/api/session", methods=["POST"])
def new_session():
    session_id = uuid.uuid4().hex[:12]
    SESSIONS[session_id] = {
        "reference_path": None,
        "input_paths": [],
        "all_signals": [],
        "fs": None,
        "report_results": [],
        "report_json_path": None,
        "media_dir": None,
        "last_switches": None,
        "last_switches_media_dir": None,
    }
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
    if not session_id or session_id not in SESSIONS:
        return jsonify({"error": "Invalid or missing session_id"}), 400

    state = SESSIONS[session_id]
    sdir = session_dir(session_id)

    reference_file = request.files.get("reference")
    input_files = request.files.getlist("inputs")
    if not reference_file or not input_files:
        return jsonify({"error": "A reference file and at least one source file are required."}), 400

    sync_mode = request.form.get("sync_mode", DEFAULT_SYNC_MODE)
    drift_correct = request.form.get("drift_correct", "false").lower() == "true"
    drift_window = float(request.form.get("drift_window", DEFAULT_DRIFT_WINDOW_SEC))

    # Save uploaded files
    ref_filename = secure_filename(reference_file.filename)
    ref_path = os.path.join(sdir, ref_filename)
    reference_file.save(ref_path)
    state["reference_path"] = ref_path

    input_paths = []
    for f in input_files:
        fname = secure_filename(f.filename)
        fpath = os.path.join(sdir, fname)
        f.save(fpath)
        input_paths.append(fpath)
    state["input_paths"] = input_paths
    state["media_dir"] = sdir

    try:
        # Extract all audio signals
        ref_wav = extract_audio(ref_path)
        sr_ref, ref_sig = load_wav(ref_wav)

        all_signals = [ref_sig]
        all_labels = ["Reference"]
        all_files = [os.path.basename(ref_path)]
        all_paths = [ref_path]

        robustness_flags = {}
        for i, src_path in enumerate(input_paths, start=1):
            label = f"Camera {chr(64 + i)}" if i <= 26 else f"Source {i}"
            src_wav = extract_audio(src_path)
            sr_src, src_sig = load_wav(src_wav)

            # Pre-flight checks
            sr_ok, sr_msg = check_sample_rates(sr_ref, sr_src)
            valid, flags = preflight_media_check(src_path, src_sig, sr_src)
            if flags:
                robustness_flags[label] = flags

            all_signals.append(src_sig)
            all_labels.append(label)
            all_files.append(os.path.basename(src_path))
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
    """Export offset-aligned FCPXML multicam timeline."""
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    fps = float(data.get("fps", 25))
    state = SESSIONS.get(session_id)
    if not state or not state.get("report_json_path"):
        return jsonify({"error": "Run sync analysis first."}), 400

    sdir = session_dir(session_id)
    out_path = os.path.join(sdir, "timeline.fcpxml")
    try:
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)



