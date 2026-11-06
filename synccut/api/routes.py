"""Flask route blueprints for SyncCut HTTP API and pages."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import os
import re
import subprocess
import threading
import traceback
import uuid
import time
from tempfile import TemporaryDirectory
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, send_file, session
from werkzeug.utils import secure_filename

from synccut.workers.tasks import run_sync_task, generate_proxies_task
from synccut.workers.celery_app import celery_app
from synccut.workers.job_control import (
    JobCancelled,
    get_last_progress,
    redis_client,
    request_cancel,
    clear_partial_audio,
)
from celery.result import AsyncResult
from synccut.ai.rough_cut import export_roughcut_fcpxml, generate_active_speaker_roughcut
from synccut.core.confidence import badge_and_status_from_confidence
from synccut.core.robustness import preflight_media_check
from synccut.core.sync_engine import load_wav
from synccut.core.sync_core import sync_files
from synccut.export.fcp7_exporter import export_fcp7_xml
from synccut.export.timeline_builder import build_timeline, export_timeline
from synccut.paths import get_sessions_dir, get_base_dir, get_ffmpeg_path
from synccut.api.tier_limits import check_tier_limits

bp = Blueprint("synccut", __name__)
ALLOWED_MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".m2ts",
    ".ts", ".mpg", ".mpeg", ".3gp", ".wmv", ".mp3", ".wav", ".m4a",
    ".aac", ".flac", ".ogg",
}

# In-memory session store — keyed per browser session (single-worker only).
SESSIONS: dict = {}


def _get_current_user():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    # THE FIX: Allow the token to be passed as a URL parameter for <video> tags
    token = token or request.args.get("token", "") or session.get("auth_token", "")
    if not token:
        return None
    from synccut.api.db import get_user_by_token
    return get_user_by_token(token)


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = _get_current_user()
        if not user:
            return jsonify({"error": "Authentication required."}), 401
        g.current_user = user
        return view(*args, **kwargs)
    return wrapped


def _upload_root() -> str:
    try:
        from flask import current_app
        return current_app.config.get("UPLOAD_ROOT", str(get_sessions_dir()))
    except Exception:
        return str(get_sessions_dir())


def _app_root() -> str:
    try:
        from flask import current_app
        return current_app.config.get("APP_ROOT", str(get_base_dir()))
    except Exception:
        return str(get_base_dir())


def session_dir(session_id: str) -> str:
    root = os.path.realpath(_upload_root())
    d = os.path.realpath(os.path.join(root, session_id))
    if os.path.commonpath([root, d]) != root:
        raise ValueError("Invalid session identifier.")
    os.makedirs(d, exist_ok=True)
    return d


def _claim_session(session_id: str, user_id: str):
    if not isinstance(session_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", session_id
    ):
        return None, (jsonify({"error": "Missing session_id."}), 400)
    try:
        sdir = session_dir(session_id)
    except ValueError:
        return None, (jsonify({"error": "Invalid session identifier."}), 400)

    owner_path = os.path.join(sdir, ".owner.json")
    if os.path.isfile(owner_path):
        try:
            with open(owner_path, "r", encoding="utf-8") as owner_file:
                owner_id = json.load(owner_file).get("user_id")
        except (OSError, json.JSONDecodeError, AttributeError):
            return None, (jsonify({"error": "Session ownership could not be verified."}), 403)
        if owner_id != user_id:
            return None, (jsonify({"error": "This session belongs to another account."}), 403)
        return sdir, None

    with os.scandir(sdir) as entries:
        if next(entries, None) is not None:
            return None, (jsonify({"error": "This session cannot be claimed."}), 403)
    with open(owner_path, "w", encoding="utf-8") as owner_file:
        json.dump({"user_id": user_id}, owner_file)
    return sdir, None


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
                    report = json.load(f)
                    report_results = report.get("results", []) if isinstance(report, dict) else report
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


def _owned_session_dir(session_id: str):
    user = _get_current_user()
    if not user:
        return None, (jsonify({"error": "Authentication required."}), 401)
    try:
        sdir = session_dir(session_id)
    except ValueError:
        return None, (jsonify({"error": "Invalid session identifier."}), 400)
    owner_path = os.path.join(sdir, ".owner.json")
    if not os.path.isfile(owner_path):
        return None, (jsonify({"error": "Owned session not found."}), 404)
    try:
        with open(owner_path, "r", encoding="utf-8") as owner_file:
            owner_id = json.load(owner_file).get("user_id")
    except (OSError, json.JSONDecodeError, AttributeError):
        return None, (jsonify({"error": "Session ownership could not be verified."}), 403)
    if owner_id != user["id"]:
        return None, (jsonify({"error": "This session belongs to another account."}), 403)
    return sdir, None


@bp.route("/")
def landing():
    return render_template("index.html")


@bp.route("/login", methods=["GET", "POST"])
def browser_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if email and password:
            from synccut.api.db import authenticate_user
            user = authenticate_user(email, password)
            if user:
                session["auth_token"] = user["token"]
                return redirect("/app")
        return render_template("login.html", error="Invalid email or password.", studio_url=_studio_url())
    return render_template("login.html", studio_url=_studio_url())


def _studio_url() -> str:
    return current_app.config.get("STUDIO_URL", "http://localhost:5173")


@bp.route("/app")
def dashboard():
    if not _get_current_user():
        return redirect("/login")
    return render_template("dashboard.html")


@bp.route("/api/waitlist", methods=["POST"])
def waitlist_signup():
    """Handle early access / beta waitlist signup requests."""
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        email = data.get("email", "").strip()
        nle = data.get("nle", "").strip()
        cameras = data.get("cameras", "").strip()
        log_dir = os.path.join(_app_root(), "uploads")
        os.makedirs(log_dir, exist_ok=True)
        waitlist_file = os.path.join(log_dir, "waitlist.jsonl")
        with open(waitlist_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"email": email, "nle": nle, "cameras": cameras}) + "\n")
        return jsonify({"status": "ok", "message": "Successfully added to beta waitlist."})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.route("/api/session", methods=["POST"])
def new_session():
    session_id = uuid.uuid4().hex[:12]
    get_session(session_id)
    return jsonify({"session_id": session_id})


@bp.route("/api/sync", methods=["POST"])
@require_auth
@check_tier_limits("upload")
def run_sync():
    """
    Global multi-source sync.
    Accepts: reference file, N input files, sync_mode, drift_correct flag.
    Returns: sync report JSON with calibrated confidence badges and drift info.
    """
    session_id = request.form.get("session_id")
    user = _get_current_user()
    sdir, ownership_error = _claim_session(session_id, user["id"])
    if ownership_error:
        return ownership_error
    state = get_session(session_id)
    if not state:
        return jsonify({"error": "Invalid or missing session_id"}), 400

    reference_file = request.files.get("reference")
    input_files = request.files.getlist("inputs")
    if not reference_file or not input_files:
        return jsonify({"error": "A reference file and at least one source file are required."}), 400
    incoming_files = [reference_file, *input_files]
    if not 2 <= len(incoming_files) <= 8:
        return jsonify({"error": "Select between 2 and 8 media files."}), 400

    meta_raw = request.form.get("metadata")
    client_meta = {}
    if meta_raw:
        try:
            client_meta = json.loads(meta_raw)
        except Exception:
            client_meta = {}

    ref_orig_name = client_meta.get("reference_name") or reference_file.filename
    input_orig_names = client_meta.get("input_names", [])
    filenames = []
    for uploaded_file in incoming_files:
        filename = secure_filename(uploaded_file.filename)
        if not filename or os.path.splitext(filename)[1].lower() not in ALLOWED_MEDIA_EXTENSIONS:
            return jsonify({"error": f"Unsupported media file: {uploaded_file.filename or 'unnamed file'}."}), 415
        filenames.append(filename)
    target_paths = [os.path.join(sdir, filename) for filename in filenames]
    if len(set(target_paths)) != len(target_paths) or any(os.path.exists(path) for path in target_paths):
        return jsonify({"error": "This session already contains that file; use a new session."}), 409

    ref_path = target_paths[0]
    input_paths = target_paths[1:]
    saved_paths = []
    try:
        for uploaded_file, target_path in zip(incoming_files, target_paths):
            uploaded_file.save(target_path)
            saved_paths.append(target_path)
    except OSError as error:
        for path in saved_paths:
            os.remove(path)
        return jsonify({"error": f"Could not save uploaded media: {error}"}), 400
    from synccut.core.quota import enforce_limits
    try:
        enforce_limits(user["id"], target_paths)
    except PermissionError as error:
        for path in saved_paths:
            os.remove(path)
        return jsonify({"error": str(error)}), 403
    except ValueError as error:
        for path in saved_paths:
            os.remove(path)
        return jsonify({"error": str(error)}), 400
    state["reference_path"] = ref_path
    state["input_paths"] = input_paths
    state["media_dir"] = sdir

    try:
        all_paths = [ref_path] + input_paths
        labels = ["Reference"] + [
            f"Camera {chr(64 + i)}" if i <= 26 else f"Source {i}"
            for i in range(1, len(all_paths))
        ]
        sync_result = sync_files(
            all_paths,
            cache_dir=os.path.join(sdir, "_sync_audio"),
            names=labels,
        )
        cameras = sync_result["cameras"]
        all_files = [os.path.basename(ref_orig_name)] + [
            os.path.basename(input_orig_names[i]) if i < len(input_orig_names)
            else os.path.basename(path)
            for i, path in enumerate(input_paths)
        ]
        results = []
        for idx, label in enumerate(labels):
            camera = cameras[label]
            drift_ppm = camera["drift_ppm"]
            drift_ms_per_hour = drift_ppm * 3.6
            confidence = camera["link_confidence"]
            badge, status = badge_and_status_from_confidence(confidence, drift_ms_per_hour)
            results.append({
                "source": label,
                "file": all_files[idx],
                "offset_s": camera["offset_s"],
                "offset_sec": camera["offset_s"],
                "drift_ppm": drift_ppm,
                "drift_ms_per_hour": drift_ms_per_hour,
                "confidence": confidence,
                "link_confidence": confidence,
                "badge": badge,
                "status": status,
                "robustness_flags": [],
            })

        state["all_signals"] = []
        state["fs"] = 16000
        state["report_results"] = results
        report_path = os.path.join(sdir, "sync_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump({
                "cameras": cameras,
                "loop_error_s": sync_result["loop_error_s"],
                "rows": sync_result["rows"],
                "results": results,
            }, f, indent=2)
        state["report_json_path"] = report_path

        try:
            from synccut.media.mixdown import build_master_mixdown
            build_master_mixdown(
                sync_result["audio_paths"],
                [cameras[name]["offset_s"] for name in labels],
                os.path.join(sdir, "master_mix.wav"),
                target_sr=16000,
            )
        except Exception:
            current_app.logger.exception("Master mixdown failed")

        return jsonify({
            "results": results,
            "rows": sync_result["rows"],
            "cameras": cameras,
            "loop_error_s": sync_result["loop_error_s"],
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.route("/api/sync_async", methods=["POST"])
@require_auth
@check_tier_limits("upload")
def run_sync_async():
    # Check both form data (for files) and JSON (for simple triggers)
    data = request.get_json(silent=True) or request.form
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    user = _get_current_user()
    sdir, ownership_error = _claim_session(session_id, user["id"])
    if ownership_error:
        return ownership_error

    # If React sends files again, save them. Otherwise, look in the directory.
    reference_file = request.files.get("reference")
    input_files = request.files.getlist("inputs")

    if reference_file and input_files:
        incoming_files = [reference_file, *input_files]
        if not 2 <= len(incoming_files) <= 8:
            return jsonify({"error": "Select between 2 and 8 media files."}), 400
        filenames = []
        for uploaded_file in incoming_files:
            filename = secure_filename(uploaded_file.filename)
            if not filename or os.path.splitext(filename)[1].lower() not in ALLOWED_MEDIA_EXTENSIONS:
                return jsonify({"error": f"Unsupported media file: {uploaded_file.filename or 'unnamed file'}."}), 415
            filenames.append(filename)
        target_paths = [os.path.join(sdir, filename) for filename in filenames]
        if len(set(target_paths)) != len(target_paths) or any(os.path.exists(path) for path in target_paths):
            return jsonify({"error": "This session already contains that file; use a new session."}), 409
        uploaded_paths = []
        try:
            for uploaded_file, target_path in zip(incoming_files, target_paths):
                uploaded_file.save(target_path)
                uploaded_paths.append(target_path)
        except OSError as error:
            for path in uploaded_paths:
                os.remove(path)
            return jsonify({"error": f"Could not save uploaded media: {error}"}), 400
        ref_path = target_paths[0]
        input_paths = target_paths[1:]
    else:
        uploaded_paths = []
        # Fallback: Use the files already uploaded in the /api/upload step
        import glob
        all_files = glob.glob(os.path.join(sdir, "*.mp4"))
        if len(all_files) < 2:
            return jsonify({"error": "Need at least 2 videos to sync"}), 400
        ref_path = all_files[0]
        input_paths = all_files[1:]

    from synccut.core.quota import enforce_limits
    try:
        enforce_limits(user["id"], [ref_path, *input_paths])
    except PermissionError as error:
        for path in uploaded_paths:
            os.remove(path)
        return jsonify({"error": str(error)}), 403
    except ValueError as error:
        for path in uploaded_paths:
            os.remove(path)
        return jsonify({"error": str(error)}), 400

    try:
        from synccut.workers.tasks import run_sync_task
        task = run_sync_task.delay(session_id, {}, ref_path, input_paths)
        return jsonify({"job_id": task.id}), 202
    except Exception:
        import threading
        job_id = f"local-sync-{uuid.uuid4().hex[:12]}"
        LOCAL_JOBS[job_id] = {"status": "PENDING"}
        LOCAL_CANCEL_EVENTS[job_id] = threading.Event()
        t = threading.Thread(
            target=_run_local_sync_job,
            args=(job_id, session_id, ref_path, input_paths),
            daemon=True,
        )
        t.start()
        return jsonify({"job_id": job_id}), 202


# In-memory local task registry for fallback when Redis is offline
LOCAL_JOBS: dict = {}
LOCAL_CANCEL_EVENTS: dict = {}


def _store_local_progress(job_id: str, current, total, status: str):
    metadata = {"status": status}
    if current is not None and total is not None:
        metadata.update({"current": current, "total": total})
    previous = LOCAL_JOBS.get(job_id, {}).get("metadata", {})
    previous_snapshot = {
        key: value for key, value in previous.items() if key != "changed_at"
    }
    metadata["changed_at"] = (
        previous.get("changed_at", time.time())
        if previous_snapshot == metadata
        else time.time()
    )
    LOCAL_JOBS[job_id] = {"status": "PROGRESS", "metadata": metadata}


def _run_local_proxy_job(job_id: str, session_id: str, file_paths: list):
    try:
        from synccut.media.proxy_gen import generate_proxy
        proxy_dir = os.path.join(get_sessions_dir(), session_id, "proxies")
        LOCAL_JOBS[job_id] = {
            "status": "PROGRESS",
            "metadata": {"current": 0, "total": len(file_paths), "status": "Starting proxies"},
        }
        results = []
        for idx, path in enumerate(file_paths):
            LOCAL_JOBS[job_id]["metadata"] = {
                "current": idx + 1,
                "total": len(file_paths),
                "status": f"Processing {os.path.basename(path)}",
            }
            try:
                proxy_path = generate_proxy(path, proxy_dir)
                results.append({"original": path, "proxy": proxy_path})
            except Exception:
                pass
        LOCAL_JOBS[job_id] = {
            "status": "SUCCESS",
            "result": {"status": "Proxy generation complete", "proxies": results},
        }
    except Exception as e:
        LOCAL_JOBS[job_id] = {"status": "FAILURE", "metadata": {"status": str(e)}}


def _run_local_sync_job(job_id: str, session_id: str, ref_path: str, input_paths: list):
    cancel_event = LOCAL_CANCEL_EVENTS.setdefault(job_id, threading.Event())

    def check_local_cancel():
        if cancel_event.is_set():
            raise JobCancelled(f"Job {job_id} was cancelled.")

    def report_progress(current, total, status):
        check_local_cancel()
        _store_local_progress(job_id, current, total, status)

    try:
        report_progress(None, None, "Decoding camera audio")
        result = run_sync_task(
            session_id,
            {},
            ref_path,
            input_paths,
            progress_callback=report_progress,
            cancel_check=check_local_cancel,
        )
        LOCAL_JOBS[job_id] = {
            "status": "SUCCESS",
            "result": result,
        }
    except JobCancelled as e:
        clear_partial_audio(os.path.join(get_sessions_dir(), session_id, "_sync_audio"))
        LOCAL_JOBS[job_id] = {"status": "REVOKED", "metadata": {"status": str(e)}}
    except Exception as e:
        LOCAL_JOBS[job_id] = {"status": "FAILURE", "metadata": {"status": str(e)}}
    finally:
        LOCAL_CANCEL_EVENTS.pop(job_id, None)


@bp.route("/api/job/status", methods=["GET"])
def job_status():
    job_id = request.args.get("job_id")
    if not job_id:
        return jsonify({"error": "Missing job_id"}), 400

    # 1. Check local thread runner first
    if job_id in LOCAL_JOBS:
        local_info = LOCAL_JOBS[job_id]
        status = local_info.get("status", "PENDING")
        metadata = local_info.get("metadata")
        if (
            status == "PROGRESS"
            and isinstance(metadata, dict)
            and time.time() - float(metadata.get("changed_at", time.time())) > 90
        ):
            status = "STALLED"
        response = {
            "job_id": job_id,
            "status": status,
        }
        if metadata is not None:
            response["metadata"] = {
                key: value for key, value in metadata.items() if key != "changed_at"
            }
        if local_info.get("result") is not None:
            response["result"] = local_info["result"]
        return jsonify(response)

    # 2. Check Celery / Redis
    try:
        redis_client().ping()
        task = AsyncResult(job_id, app=celery_app)
        state = task.state
        response = {"job_id": job_id, "status": state}
        if state == "PROGRESS":
            metadata = task.info
            if isinstance(metadata, dict) and metadata:
                response["metadata"] = metadata
            progress = get_last_progress(job_id)
            if progress and time.time() - float(progress.get("changed_at", time.time())) > 90:
                response["status"] = "STALLED"
                if isinstance(metadata, dict):
                    response["metadata"] = metadata
        elif state == "SUCCESS":
            result = task.result
            response["result"] = result
            if isinstance(result, dict):
                session_id = result.get("session_id")
                if isinstance(session_id, str) and session_id:
                    sdir = session_dir(session_id)
                    session_state = get_session(session_id)
                    report_path = os.path.join(sdir, "sync_report.json")
                    session_state.update({
                        "media_dir": sdir,
                        "report_json_path": report_path,
                        "report_results": result.get("sync_data", []),
                        "segments": result.get("segments", []),
                        "fs": 16000,
                    })
                    session_state["last_switches"] = result.get("segments", [])
                    session_state["last_switches_media_dir"] = sdir
        elif state == "FAILURE":
            response["error"] = str(task.info)
        return jsonify(response)
    except Exception:
        return jsonify({"status": "UNKNOWN"})


@bp.route("/api/job/cancel", methods=["POST"])
def cancel_job():
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    if not job_id:
        return jsonify({"error": "Missing job_id"}), 400

    if job_id in LOCAL_CANCEL_EVENTS:
        LOCAL_CANCEL_EVENTS[job_id].set()
        return jsonify({"job_id": job_id, "status": "CANCEL_REQUESTED"}), 202

    try:
        redis = redis_client()
        redis.ping()
        task = AsyncResult(job_id, app=celery_app)
        if task.state in {"SUCCESS", "FAILURE", "REVOKED"}:
            return jsonify({"job_id": job_id, "status": task.state}), 409
        request_cancel(job_id)
        return jsonify({"job_id": job_id, "status": "CANCEL_REQUESTED"}), 202
    except Exception:
        return jsonify({"job_id": job_id, "status": "UNKNOWN", "error": "Job backend unavailable"}), 503


def _run_local_full_pipeline_job(job_id: str, session_id: str, file_paths: list):
    """Local thread fallback running the same disk-backed sync and AI stages."""
    cancel_event = LOCAL_CANCEL_EVENTS.setdefault(job_id, threading.Event())

    def check_local_cancel():
        if cancel_event.is_set():
            raise JobCancelled(f"Job {job_id} was cancelled.")

    def report_progress(current, total, status):
        check_local_cancel()
        _store_local_progress(job_id, current, total, status)

    try:
        sdir = session_dir(session_id)
        if not file_paths:
            raise ValueError("At least one media file is required.")
        report_progress(None, None, "Decoding camera audio")
        from synccut.workers.tasks import run_ai_cut_task, run_sync_task
        sync_result = run_sync_task(
            session_id,
            {},
            file_paths[0],
            file_paths[1:],
            progress_callback=report_progress,
            cancel_check=check_local_cancel,
        )
        report_path = os.path.join(sdir, "sync_report.json")
        state = get_session(session_id)
        state.update({
            "report_json_path": report_path,
            "report_results": sync_result["sync_data"],
            "all_signals": [],
            "fs": 16000,
        })
        check_local_cancel()
        report_progress(None, None, "Detecting rough-cut segments")
        cut_result = run_ai_cut_task(
            session_id,
            file_paths,
            progress_callback=report_progress,
            cancel_check=check_local_cancel,
        )
        segments = cut_result["segments"]
        LOCAL_JOBS[job_id] = {
            "status": "SUCCESS",
            "result": {
                "status": "Ready for Review",
                "session_id": session_id,
                "sync_data": sync_result["sync_data"],
                "rows": sync_result["rows"],
                "cameras": sync_result["cameras"],
                "master_source": sync_result.get("master_source"),
                "loop_error_s": sync_result["loop_error_s"],
                "segments": segments,
                "master_audio_url": sync_result["master_audio_url"],
            },
        }

    except JobCancelled as e:
        clear_partial_audio(os.path.join(session_dir(session_id), "_sync_audio"))
        LOCAL_JOBS[job_id] = {"status": "REVOKED", "metadata": {"status": str(e)}}
    except Exception as e:
        traceback.print_exc()
        LOCAL_JOBS[job_id] = {
            "status": "FAILURE",
            "metadata": {"status": f"Pipeline error: {str(e)}"},
        }
    finally:
        LOCAL_CANCEL_EVENTS.pop(job_id, None)


@bp.route("/api/upload", methods=["POST"])
@require_auth
@check_tier_limits("upload")
def upload_files():
    """Validate and ingest 2-8 supported media files for the authenticated user."""
    session_id = request.form.get("session_id")
    if not session_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", session_id):
        return jsonify({"error": "Invalid or missing session_id."}), 400

    files = [file for file in request.files.getlist("files") if file and file.filename]
    if not 2 <= len(files) <= 8:
        return jsonify({"error": "Select between 2 and 8 video or audio files."}), 400

    allowed_extensions = ALLOWED_MEDIA_EXTENSIONS
    safe_names = []
    for file in files:
        filename = secure_filename(file.filename)
        extension = os.path.splitext(filename)[1].lower()
        if not filename or extension not in allowed_extensions:
            return jsonify({"error": f"Unsupported media file: {file.filename or 'unnamed file'}."}), 415
        safe_names.append(filename)

    user = _get_current_user()
    try:
        sdir = session_dir(session_id)
    except ValueError:
        return jsonify({"error": "Invalid session_id."}), 400
    owner_path = os.path.join(sdir, ".owner.json")
    if os.path.exists(owner_path):
        try:
            with open(owner_path, "r", encoding="utf-8") as owner_file:
                owner_id = json.load(owner_file).get("user_id")
        except (OSError, json.JSONDecodeError, AttributeError):
            return jsonify({"error": "Upload session ownership could not be verified."}), 403
        if owner_id != user["id"]:
            return jsonify({"error": "This upload session belongs to another account."}), 403
    else:
        with os.scandir(sdir) as entries:
            has_existing_files = next(entries, None) is not None
        if has_existing_files:
            return jsonify({"error": "This upload session already contains files and cannot be claimed."}), 403
        with open(owner_path, "w", encoding="utf-8") as owner_file:
            json.dump({"user_id": user["id"]}, owner_file)
    from synccut.core.quota import enforce_limits

    final_paths = [
        os.path.join(sdir, f"{index:02d}_{filename}")
        for index, filename in enumerate(safe_names, start=1)
    ]
    saved_paths = []
    with TemporaryDirectory(prefix=".upload-", dir=sdir) as staging_dir:
        staged_paths = []
        try:
            for index, (file, filename) in enumerate(zip(files, safe_names), start=1):
                staged_path = os.path.join(staging_dir, f"{index:02d}_{filename}")
                file.save(staged_path)
                if not os.path.isfile(staged_path) or os.path.getsize(staged_path) == 0:
                    raise ValueError(f"{filename} is empty or could not be saved.")
                staged_paths.append(staged_path)
        except (OSError, ValueError) as error:
            return jsonify({"error": f"Could not save uploaded media: {error}"}), 400

        replaced_paths = set(final_paths)
        media_paths = []
        with os.scandir(sdir) as entries:
            for entry in entries:
                if (
                    entry.is_file()
                    and entry.path not in replaced_paths
                    and os.path.splitext(entry.name)[1].lower() in allowed_extensions
                ):
                    media_paths.append(entry.path)
        media_paths.extend(staged_paths)
        try:
            enforce_limits(user["id"], media_paths)
        except PermissionError as error:
            return jsonify({"error": str(error)}), 403
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

        backups = {}
        moved_paths = []
        try:
            for index, final_path in enumerate(final_paths, start=1):
                if os.path.isfile(final_path):
                    backup_path = os.path.join(staging_dir, f"backup-{index}")
                    os.replace(final_path, backup_path)
                    backups[final_path] = backup_path
            for staged_path, final_path in zip(staged_paths, final_paths):
                os.replace(staged_path, final_path)
                moved_paths.append(final_path)
        except OSError as error:
            for moved_path in moved_paths:
                os.remove(moved_path)
            for original_path, backup_path in backups.items():
                if os.path.exists(backup_path):
                    os.replace(backup_path, original_path)
            return jsonify({"error": f"Could not finalize uploaded media: {error}"}), 400
        saved_paths = final_paths

    # Trigger Master Full Pipeline Task (Celery or fallback)
        # Trigger Master Full Pipeline Task (Celery or fallback)
    try:
        from synccut.workers.tasks import full_pipeline_task
        from synccut.workers.job_control import redis_client

        # WHY: We ping Redis first. If Redis is dead, this throws an error instantly
        # instead of hanging for 30 seconds trying to queue a task.
        redis_client().ping()
        
        task = full_pipeline_task.delay(session_id, saved_paths)
        return jsonify({"message": "Pipeline initiated via Celery", "job_id": task.id, "file_count": len(saved_paths)}), 202
        
    except Exception as e:
        # WHY: If Redis is down, we fall back to a local Python thread immediately.
        print(f"[Fallback] Celery/Redis unavailable. Running local thread. Error: {e}")
        
        job_id = f"pipeline-{uuid.uuid4().hex[:12]}"
        LOCAL_JOBS[job_id] = {"status": "PENDING"}
        LOCAL_CANCEL_EVENTS[job_id] = threading.Event()
        try:
            app = current_app._get_current_object()
        except Exception:
            app = None

        def _worker_wrapper():
            if app:
                with app.app_context():
                    _run_local_full_pipeline_job(job_id, session_id, saved_paths)
            else:
                _run_local_full_pipeline_job(job_id, session_id, saved_paths)

        t = threading.Thread(
            target=_worker_wrapper,
            daemon=True,
        )
        t.start()
        return jsonify({"message": "Pipeline initiated (local daemon)", "job_id": job_id, "file_count": len(saved_paths)}), 202

@bp.route("/api/session/<session_id>/master_audio", methods=["GET"])
@require_auth
def master_audio(session_id):
    """Deliverable 2: stream the mixed-down, sync-corrected master WAV."""
    sdir, error_response = _owned_session_dir(session_id)
    if error_response:
        return error_response
    mix_path = os.path.join(sdir, "master_mix.wav")
    if not os.path.exists(mix_path):
        return jsonify({"error": "Master mix not ready. Wait for sync to finish."}), 404
    return send_file(mix_path, mimetype="audio/wav", conditional=True)


@bp.route("/api/session/<session_id>/waveform/<int:index>", methods=["GET"])
@require_auth
def camera_waveform(session_id, index):
    """Serve compact 100 Hz peak data for one source camera."""
    sdir, error_response = _owned_session_dir(session_id)
    if error_response:
        return error_response

    report_path = os.path.join(sdir, "sync_report.json")
    if not os.path.isfile(report_path):
        return jsonify({"error": "Sync report is not ready."}), 404
    try:
        with open(report_path, "r", encoding="utf-8") as report_file:
            report = json.load(report_file)
    except (OSError, json.JSONDecodeError) as error:
        return jsonify({"error": f"Could not read sync report: {error}"}), 500
    waveform_files = report.get("waveform_files", [])
    if not isinstance(waveform_files, list) or index < 0 or index >= len(waveform_files):
        return jsonify({"error": "Waveform is unavailable for this camera."}), 404

    filename = waveform_files[index]
    if not isinstance(filename, str) or os.path.basename(filename) != filename:
        return jsonify({"error": "Invalid waveform reference in sync report."}), 500
    waveform_root = os.path.realpath(os.path.join(sdir, "_sync_audio"))
    waveform_path = os.path.realpath(os.path.join(waveform_root, filename))
    if os.path.commonpath([waveform_root, waveform_path]) != waveform_root:
        return jsonify({"error": "Invalid waveform path."}), 500
    if not os.path.isfile(waveform_path):
        return jsonify({"error": "Waveform data is missing."}), 404
    response = send_file(waveform_path, mimetype="application/octet-stream", conditional=True)
    response.headers["X-Waveform-Rate"] = "100"
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@bp.route("/api/session/<session_id>/media/<int:index>", methods=["GET"])
@require_auth
def session_media(session_id, index):
    """Stream an uploaded camera source for reloaded project sessions."""
    sdir, error_response = _owned_session_dir(session_id)
    if error_response:
        return error_response
    report_path = os.path.join(sdir, "sync_report.json")
    if not os.path.isfile(report_path):
        return jsonify({"error": "Sync report is not ready."}), 404
    try:
        with open(report_path, "r", encoding="utf-8") as report_file:
            results = json.load(report_file).get("results", [])
    except (OSError, json.JSONDecodeError, AttributeError) as error:
        return jsonify({"error": f"Could not read sync report: {error}"}), 500
    if not isinstance(results, list) or index < 0 or index >= len(results):
        return jsonify({"error": "Camera source is unavailable."}), 404
    filename = results[index].get("file")
    if not isinstance(filename, str) or os.path.basename(filename) != filename:
        return jsonify({"error": "Invalid camera source reference."}), 500
    media_root = os.path.realpath(sdir)
    media_path = os.path.realpath(os.path.join(media_root, filename))
    if os.path.commonpath([media_root, media_path]) != media_root:
        return jsonify({"error": "Invalid camera source path."}), 500
    if not os.path.isfile(media_path):
        return jsonify({"error": "Camera source file is missing."}), 404
    return send_file(
        media_path,
        mimetype=mimetypes.guess_type(media_path)[0] or "application/octet-stream",
        conditional=True,
    )


@bp.route("/api/session/<session_id>/thumbnail/<int:index>", methods=["GET"])
@require_auth
def session_thumbnail(session_id, index):
    """Extract and cache a real frame for a timeline filmstrip."""
    sdir, error_response = _owned_session_dir(session_id)
    if error_response:
        return error_response
    try:
        requested_time = float(request.args.get("time", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "A valid non-negative thumbnail time is required."}), 400
    if not (requested_time >= 0 and requested_time < float("inf")):
        return jsonify({"error": "A valid non-negative thumbnail time is required."}), 400

    report_path = os.path.join(sdir, "sync_report.json")
    try:
        with open(report_path, "r", encoding="utf-8") as report_file:
            results = json.load(report_file).get("results", [])
    except (OSError, json.JSONDecodeError, AttributeError) as error:
        return jsonify({"error": f"Could not read sync report: {error}"}), 500
    if not isinstance(results, list) or index < 0 or index >= len(results):
        return jsonify({"error": "Camera source is unavailable."}), 404

    row = results[index]
    duration = row.get("duration_sec")
    if duration is not None and requested_time > float(duration):
        return jsonify({"error": "Thumbnail time is outside this camera's footage."}), 416
    filename = row.get("file")
    if not isinstance(filename, str) or os.path.basename(filename) != filename:
        return jsonify({"error": "Invalid camera source reference."}), 500
    media_root = os.path.realpath(sdir)
    media_path = os.path.realpath(os.path.join(media_root, filename))
    if os.path.commonpath([media_root, media_path]) != media_root:
        return jsonify({"error": "Invalid camera source path."}), 500
    if not os.path.isfile(media_path):
        return jsonify({"error": "Camera source file is missing."}), 404

    media_stat = os.stat(media_path)
    # Timeline thumbnails are spaced at 10-second intervals.
    frame_time = round(requested_time / 10.0) * 10.0
    if duration is not None:
        frame_time = min(frame_time, max(0.0, float(duration) - 0.001))
    cache_key = hashlib.sha256(
        f"{media_path}\0{media_stat.st_size}\0{media_stat.st_mtime_ns}\0{frame_time}".encode("utf-8")
    ).hexdigest()
    thumbnail_dir = os.path.join(sdir, "_thumbnails")
    os.makedirs(thumbnail_dir, exist_ok=True)
    thumbnail_path = os.path.join(thumbnail_dir, f"{cache_key}.jpg")
    if not os.path.isfile(thumbnail_path):
        partial_path = f"{thumbnail_path}.{os.getpid()}.part.jpg"
        command = [
            get_ffmpeg_path(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-ss", f"{frame_time:.3f}", "-i", media_path,
            "-frames:v", "1",
            "-vf", "scale=240:136:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=240:136:(ow-iw)/2:(oh-ih)/2",
            "-q:v", "5", "-y", partial_path,
        ]
        try:
            subprocess.run(command, capture_output=True, check=True, timeout=30)
            if not os.path.isfile(partial_path) or os.path.getsize(partial_path) == 0:
                if os.path.exists(partial_path):
                    os.remove(partial_path)
                return jsonify({"error": "FFmpeg produced no video thumbnail."}), 422
            os.replace(partial_path, thumbnail_path)
        except subprocess.TimeoutExpired:
            if os.path.exists(partial_path):
                os.remove(partial_path)
            return jsonify({"error": "Thumbnail extraction timed out."}), 504
        except (OSError, subprocess.CalledProcessError) as error:
            if os.path.exists(partial_path):
                os.remove(partial_path)
            current_app.logger.warning("Thumbnail extraction failed for %s: %s", filename, error)
            return jsonify({"error": "Could not decode a thumbnail from this video."}), 422

    response = send_file(thumbnail_path, mimetype="image/jpeg", conditional=True)
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


@bp.route("/api/session/<session_id>/project", methods=["GET", "PUT"])
@require_auth
def session_project(session_id):
    """Load or atomically save the user's versioned non-destructive edit model."""
    sdir, error_response = _owned_session_dir(session_id)
    if error_response:
        return error_response
    project_path = os.path.join(sdir, "project.json")
    if request.method == "GET":
        if not os.path.isfile(project_path):
            return jsonify({"error": "Project file not found."}), 404
        try:
            with open(project_path, "r", encoding="utf-8") as project_file:
                project = json.load(project_file)
        except (OSError, json.JSONDecodeError) as error:
            return jsonify({"error": f"Could not read project file: {error}"}), 500
        return jsonify({"project": project})

    if request.content_length and request.content_length > 5 * 1024 * 1024:
        return jsonify({"error": "Project data exceeds the 5 MB limit."}), 413
    project = request.get_json(silent=True)
    if (
        not isinstance(project, dict)
        or project.get("version") != 1
        or not isinstance(project.get("cameras"), list)
        or len(project["cameras"]) > 8
        or not isinstance(project.get("program"), list)
        or len(project["program"]) > 10000
    ):
        return jsonify({"error": "Invalid versioned project document."}), 400
    temporary_path = f"{project_path}.{threading.get_ident()}.tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as project_file:
            json.dump(project, project_file, allow_nan=False, separators=(",", ":"))
        os.replace(temporary_path, project_path)
    except (OSError, TypeError, ValueError) as error:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        return jsonify({"error": f"Could not save project file: {error}"}), 500
    return jsonify({"saved": True})


@bp.route("/api/report/download", methods=["GET"])
def download_report_json():
    session_id = request.args.get("session_id")
    state = SESSIONS.get(session_id)
    if not state or not state.get("report_json_path"):
        return jsonify({"error": "No report available for this session."}), 400
    return send_file(
        state["report_json_path"], as_attachment=True, download_name="sync_report.json"
    )


@bp.route("/api/preflight", methods=["POST"])
def preflight_diagnostics():
    """Run robustness checks on each uploaded file and return a JSON report."""
    reference_file = request.files.get("reference")
    input_files = request.files.getlist("inputs")
    if not reference_file:
        return jsonify({"error": "Reference file required for diagnostics."}), 400
    files = [("reference", reference_file)] + [
        (f"input_{i}", f) for i, f in enumerate(input_files)
    ]
    results = []
    for label, f in files:
        fname = secure_filename(f.filename)
        temp_path = os.path.join(get_sessions_dir(), "tmp_diag", fname)
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        f.save(temp_path)
        try:
            sr, sig = load_wav(temp_path)
        except Exception:
            sr, sig = None, None
        ok, flags = preflight_media_check(temp_path, sig, sr)
        results.append({"label": label, "file": fname, "valid": ok, "flags": flags})
        os.remove(temp_path)
    return jsonify({"diagnostics": results})


@bp.route("/api/review", methods=["POST"])
def review_offsets():
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    adjustments = data.get("adjustments", {})
    state = SESSIONS.get(session_id)
    if not state:
        return jsonify({"error": "Invalid session_id"}), 400
    for r in state.get("report_results", []):
        label = r.get("source")
        if label in adjustments:
            r["offset_s"] = float(adjustments[label])
            r["offset_sec"] = r["offset_s"]
            r["status"] = "Manually adjusted"
    report_path = state.get("report_json_path")
    if report_path:
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
        else:
            report = {}
        if isinstance(report, dict):
            cameras = report.setdefault("cameras", {})
            for row in state.get("report_results", []):
                camera = cameras.get(row.get("source"))
                if camera is not None:
                    camera["offset_s"] = row.get("offset_s", row.get("offset_sec"))
            report["results"] = state["report_results"]
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
        else:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(state["report_results"], f, indent=2)
    return jsonify({"status": "adjustments applied", "results": state["report_results"]})


@bp.route("/api/report/csv", methods=["GET"])
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
        "Confidence", "Badge", "Status", "Robustness_Flags",
    ])
    for r in state["report_results"]:
        writer.writerow([
            r["source"], r["file"], r["offset_sec"],
            r["drift_ms_per_hour"], r.get("drift_ci_lower", ""),
            r.get("drift_ci_upper", ""),
            r["confidence"], r["badge"], r["status"],
            "; ".join(r.get("robustness_flags", [])),
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        as_attachment=True,
        download_name="sync_confidence_report.csv",
        mimetype="text/csv",
    )


@bp.route("/api/export/timeline", methods=["POST"])
@require_auth
@check_tier_limits("export")
def export_timeline_route():
    """Export offset-aligned timeline (FCPXML, Premiere XML, AAF, or Audit PDF)."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    export_format = data.get("format", "fcpxml").lower()
    overrides = data.get("overrides", {})
    
    # This is the exact NLE state from the React frontend
    timeline_clips = data.get("timeline_clips", []) 

    if not session_id:
        return jsonify({"error": "Missing session_id."}), 400
    
    sdir = session_dir(session_id)
    report_path = os.path.join(sdir, "sync_report.json")

    if not os.path.exists(report_path) and not timeline_clips:
        return jsonify({"error": "Sync incomplete. Wait for the progress bar to hit 100%."}), 400

    # 1. Load the base project or create a new one
    project_path = os.path.join(sdir, "project.json")
    project = None
    if os.path.exists(project_path):
        try:
            with open(project_path, "r", encoding="utf-8") as project_file:
                project = json.load(project_file)
        except (OSError, json.JSONDecodeError) as error:
            return jsonify({"error": f"Could not read the saved project: {error}"}), 500

    if project is None:
        project = {"version": 1, "fps": 25, "cameras": [], "program": []}

    # 2. If React sent the NLE timeline, override the project program
    if timeline_clips:
        project["program"] = [
            {
                "camera": clip.get("name"),
                "start": float(clip.get("start", 0)),
                "end": float(clip.get("start", 0)) + float(clip.get("duration", 0)),
                "reason": clip.get("reason", "manual_nle_edit")
            }
            for clip in timeline_clips
        ]

    # 3. Validate and update FPS
    try:
        fps = float(project.get("fps", data.get("fps", 25)))
    except (TypeError, ValueError):
        return jsonify({"error": "Project frame rate must be a number."}), 400
    if not 1 <= fps <= 120:
        return jsonify({"error": "Project frame rate is outside supported bounds."}), 400

    # 4. Save the updated project to disk so it persists
    try:
        with open(project_path + ".tmp", "w", encoding="utf-8") as project_file:
            json.dump(project, project_file, allow_nan=False, separators=(",", ":"))
        os.replace(project_path + ".tmp", project_path)
    except (OSError, TypeError, ValueError) as error:
        return jsonify({"error": f"Could not save project before export: {error}"}), 500

    # 5. Save manual overrides
    if overrides:
        try:
            with open(os.path.join(sdir, "manual_overrides.json"), "w", encoding="utf-8") as f:
                json.dump(overrides, f, indent=2, allow_nan=False)
        except (OSError, TypeError, ValueError) as error:
            return jsonify({"error": f"Could not save manual overrides: {error}"}), 500

    # 6. Ensure state is populated for exporters
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "session_id": session_id,
            "media_dir": sdir,
            "report_json_path": report_path,
        }
    state = SESSIONS[session_id]
    if "media_dir" not in state:
        state["media_dir"] = sdir
    if "report_json_path" not in state:
        state["report_json_path"] = report_path

    try:
        if export_format in ("fcp7", "xmeml", "xml", "premiere"):
            out_path = os.path.join(sdir, "timeline_premiere.xml")
            export_fcp7_xml(state["report_json_path"], state["media_dir"], out_path, fps=fps)
            return send_file(out_path, as_attachment=True, download_name="timeline_premiere.xml")

        elif export_format == "aaf":
            out_path = os.path.join(sdir, "timeline.aaf")
            tl = build_timeline(state["report_json_path"], state["media_dir"], fps=fps, project=project)
            export_timeline(tl, out_path)
            return send_file(out_path, as_attachment=True, download_name="synccut_multicam.aaf")

        elif export_format == "edl":
            out_path = os.path.join(sdir, "timeline.edl")
            tl = build_timeline(state["report_json_path"], state["media_dir"], fps=fps, project=project)
            export_timeline(tl, out_path)
            return send_file(out_path, as_attachment=True, download_name="synccut_timeline.edl")

        elif export_format in ("audit_pdf", "pdf"):
            out_path = os.path.join(sdir, "sync_audit_report.pdf")
            try:
                from reportlab.lib.pagesizes import letter
                from reportlab.pdfgen import canvas
                c = canvas.Canvas(out_path, pagesize=letter)
                c.setFont("Helvetica-Bold", 16)
                c.drawString(50, 750, "SyncCut Studio - Multicam Audio Sync Audit Report")
                c.setFont("Helvetica", 10)
                c.drawString(50, 730, f"Session ID: {session_id} | Timebase: {fps} FPS")
                c.line(50, 720, 550, 720)

                with open(report_path, "r", encoding="utf-8") as rf:
                    report_data = json.load(rf)
                items = report_data.get("results", []) if isinstance(report_data, dict) else report_data
                
                y = 690
                c.setFont("Helvetica-Bold", 10)
                c.drawString(50, y, "Source")
                c.drawString(150, y, "File")
                c.drawString(320, y, "Offset (s)")
                c.drawString(400, y, "Drift (ppm)")
                c.drawString(480, y, "Status")
                y -= 20
                c.setFont("Helvetica", 9)
                for item in items:
                    offset = item.get("offset_s", item.get("offset_sec", 0.0))
                    c.drawString(50, y, str(item.get("source", "")))
                    c.drawString(150, y, str(item.get("file", ""))[:25])
                    c.drawString(320, y, f"{float(offset or 0.0):+.3f}s")
                    c.drawString(400, y, f"{float(item.get('drift_ppm', 0.0)):+.2f}")
                    c.drawString(480, y, str(item.get("state", item.get("status", "VERIFY"))))
                    y -= 18
                y -= 10
                c.setFont("Helvetica-Bold", 11)
                c.drawString(50, y, "Program edits")
                y -= 18
                c.setFont("Helvetica", 9)
                for segment in project.get("program", []):
                    if y < 60:
                        c.showPage()
                        y = 750
                        c.setFont("Helvetica", 9)
                    c.drawString(
                        50, y,
                        f"{segment.get('camera', '')}: {float(segment.get('start', 0)):.3f}s - "
                        f"{float(segment.get('end', 0)):.3f}s ({segment.get('reason', 'cut')})",
                    )
                    y -= 15
                c.save()
            except Exception as error:
                raise RuntimeError(f"Could not generate the sync audit PDF: {error}") from error
            return send_file(out_path, as_attachment=True, download_name="sync_audit_report.pdf")

        # Default: FCPXML
        out_path = os.path.join(sdir, "timeline.fcpxml")
        tl = build_timeline(state["report_json_path"], state["media_dir"], fps=fps, project=project)
        export_timeline(tl, out_path)
        return send_file(out_path, as_attachment=True, download_name="synccut_timeline.fcpxml")

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.route("/api/switches", methods=["POST"])
@require_auth
@check_tier_limits("ai_cuts")
def analyze_switches_route():
    """Generate camera switch rough cut using ASD pipeline."""
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    state = SESSIONS.get(session_id)
    if not state or not state.get("report_json_path"):
        return jsonify({"error": "Run sync analysis first."}), 400

    try:
        results = state["report_results"]
        fs = state.get("fs", 16000)
        report = {}
        report_path = state.get("report_json_path")
        if report_path and os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
        cameras = report.get("cameras", {}) if isinstance(report, dict) else {}
        known_paths = {
            os.path.basename(path): path
            for path in [state.get("reference_path"), *state.get("input_paths", [])]
            if path
        }
        ordered_paths = [state.get("reference_path"), *state.get("input_paths", [])]

        sources_data = {}
        for index, r in enumerate(results):
            media_path = known_paths.get(r.get("file"))
            if not media_path or not os.path.isfile(media_path):
                if index < len(ordered_paths) and ordered_paths[index]:
                    media_path = ordered_paths[index]
            if not media_path or not os.path.isfile(media_path):
                media_path = os.path.join(state.get("media_dir", ""), r.get("file", ""))
            if media_path and os.path.isfile(media_path):
                sources_data[r["source"]] = {
                    "file": media_path,
                    "offset_sec": float(
                        cameras.get(r["source"], {}).get(
                            "offset_s", r.get("offset_s", r.get("offset_sec", 0.0))
                        )
                    ),
                }

        if not sources_data:
            return jsonify({"error": "No synced video files are available for the rough cut."}), 400

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


@bp.route("/api/project/<project_id>/patch", methods=["POST"])
def patch_timeline(project_id):
    """
    WHY: Allows the editor to manually override the AI's camera switch decisions.
    We don't re-run the heavy AI; we just patch the JSON manifest.
    """
    data = request.get_json()
    overrides = data.get("overrides", []) # List of {start_sec, end_sec, camera}

    if not overrides:
        return jsonify({"error": "No overrides provided"}), 400

    sdir = session_dir(project_id)
    manifest_path = os.path.join(sdir, "timeline_manifest.json")

    # Load existing manifest or create a new one
    if os.path.exists(manifest_path):
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
    else:
        manifest = {"segments": []}

    # Apply the overrides
    for override in overrides:
        # In a real app, you'd logic to merge/overlap these segments intelligently.
        # For now, we just append them as highest priority.
        manifest["segments"].append({
            "start": override["start_sec"],
            "end": override["end_sec"],
            "camera": override["camera"],
            "source": "manual_override",
            "confidence": 1.0 # Manual is 100% confident
        })

    # Sort segments by start time
    manifest["segments"].sort(key=lambda x: x["start"])

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return jsonify({"status": "success", "manifest": manifest})


@bp.route("/api/export/switch-timeline", methods=["POST"])
@require_auth
@check_tier_limits("ai_cuts")
def export_switch_timeline_route():
    """Export rough cut FCPXML."""
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    fps = float(data.get("fps", 25))
    state = get_session(session_id)
    if state and not state.get("last_switches"):
        switches_path = os.path.join(session_dir(session_id), "switches.json")
        if os.path.exists(switches_path):
            try:
                with open(switches_path, "r", encoding="utf-8") as f:
                    state["last_switches"] = json.load(f)
                state.setdefault("last_switches_media_dir", state.get("media_dir", session_dir(session_id)))
            except (OSError, json.JSONDecodeError) as e:
                return jsonify({"error": f"Could not load rough-cut segments: {e}"}), 500
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


# -------------------------------------------------------------------------
# AUTHENTICATION & SECURE USER PROJECT PERSISTENCE
# -------------------------------------------------------------------------
@bp.route("/api/auth/register", methods=["POST"])
def auth_register():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required."}), 400
    email_value, password_value, name_value = (
        data.get("email"), data.get("password"), data.get("name", "")
    )
    if not isinstance(email_value, str) or not isinstance(password_value, str) or not isinstance(name_value, str):
        return jsonify({"error": "Email, password, and name must be text values."}), 400
    email = email_value.strip()
    password = password_value.strip()
    name = name_value.strip()
    if not email or len(password) < 8:
        return jsonify({"error": "Email and a password of at least 8 characters are required."}), 400
    try:
        from synccut.api.db import create_user
        user = create_user(email, name, password)
        session["auth_token"] = user["token"]
        return jsonify({"user": user, "token": user["token"]}), 201
    except Exception as e:
        return jsonify({"error": f"Registration failed: {str(e)}"}), 400


@bp.route("/api/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required."}), 400
    email_value, password_value = data.get("email"), data.get("password")
    if not isinstance(email_value, str) or not isinstance(password_value, str):
        return jsonify({"error": "Email and password must be text values."}), 400
    email = email_value.strip()
    password = password_value.strip()
    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400
    try:
        from synccut.api.db import authenticate_user
        user = authenticate_user(email, password)
        if not user:
            return jsonify({"error": "Invalid credentials."}), 401
        session["auth_token"] = user["token"]
        return jsonify({"user": user, "token": user["token"]}), 200
    except Exception as e:
        return jsonify({"error": f"Login failed: {str(e)}"}), 500


@bp.route("/api/auth/me", methods=["GET"])
def auth_me():
    user = _get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"user": user})


@bp.route("/api/auth/logout", methods=["POST"])
def auth_logout():
    from synccut.api.db import revoke_user_token
    token = request.headers.get("Authorization", "")
    token = token[7:].strip() if token.startswith("Bearer ") else session.get("auth_token", "")
    if token:
        revoke_user_token(token)
    session.clear()
    return jsonify({"status": "logged out"})


@bp.route("/api/projects", methods=["GET"])
@require_auth
def api_list_projects():
    user = _get_current_user()
    user_id = user["id"]
    from synccut.api.db import get_user_projects
    projects = get_user_projects(user_id)
    return jsonify({"projects": projects})


@bp.route("/api/projects", methods=["POST"])
@require_auth
def api_create_project():
    user = _get_current_user()
    user_id = user["id"]
    data = request.get_json(silent=True) or {}
    from synccut.api.db import create_user_project
    project = create_user_project(user_id, data)
    return jsonify({"project": project}), 201


@bp.route("/api/projects/<project_id>", methods=["DELETE"])
@require_auth
def api_delete_project(project_id):
    user = _get_current_user()
    user_id = user["id"]
    from synccut.api.db import delete_user_project
    success = delete_user_project(user_id, project_id)
    return jsonify({"success": success})


@bp.route("/api/projects/<project_id>", methods=["PATCH"])
@require_auth
def api_update_project(project_id):
    user = _get_current_user()
    user_id = user["id"]
    data = request.get_json(silent=True) or {}
    from synccut.api.db import update_user_project
    success = update_user_project(user_id, project_id, data)
    return jsonify({"success": success})


@bp.route("/api/system/storage", methods=["GET"])
def api_system_storage():
    from synccut.paths import get_storage_info
    return jsonify(get_storage_info())