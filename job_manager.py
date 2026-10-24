import os
import uuid
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from flask import jsonify
from werkzeug.utils import secure_filename

from paths import get_sessions_dir, get_user_data_dir
from extract import extract_audio
from sync_engine import solve_multi_source_sync, load_wav
from robustness import preflight_media_check, check_sample_rates
from drift import windowed_offsets, analyze_drift, correct_audio_drift_resample
from confidence import badge_and_status_from_confidence

# Global executor and job registry
_executor = None
_jobs = {}
_jobs_lock = Lock()

def start_executor(max_workers: int = 2):
    """Initialize the ThreadPoolExecutor used for background sync jobs."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=max_workers)
        print("[job_manager] Executor started with", max_workers, "workers")

def submit_job(session_id: str, payload: dict, files) -> str:
    """Enqueue a sync job.

    Args:
        session_id: Identifier of the user session.
        payload: Dictionary of form fields (as returned by ``request.form.to_dict(flat=False)``).
        files: ``werkzeug.datastructures.MultiDict`` of uploaded files.
    Returns:
        A UUID string that can be used to query job status.
    """
    job_id = uuid.uuid4().hex
    with jobs_lock:
        _jobs[job_id] = {
            "status": "queued",
            "session_id": session_id,
            "error": None,
            "result": None,
        }
    if _executor is None:
        start_executor()
    _executor.submit(_run_job, job_id, session_id, payload, files)
    return job_id

def get_status(job_id: str):
    """Return a copy of the status dictionary for the given job id, or ``None`` if unknown."""
    with jobs_lock:
        status = _jobs.get(job_id)
        if status is None:
            return None
        return status.copy()

def _update_job(job_id: str, **kwargs):
    with jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)

def _run_job(job_id: str, session_id: str, payload: dict, files):
    try:
        _update_job(job_id, status="running")
        sdir = os.path.join(get_sessions_dir(), session_id)
        os.makedirs(sdir, exist_ok=True)
        def _first(key, default=None):
            vals = payload.get(key)
            return vals[0] if vals else default
        sync_mode = _first("sync_mode", "global")
        drift_correct = _first("drift_correct", "false").lower() == "true"
        drift_window = float(_first("drift_window", "0"))
        meta_raw = _first("metadata", None)
        client_meta = {}
        if meta_raw:
            try:
                client_meta = json.loads(meta_raw)
            except Exception:
                client_meta = {}
        reference_file = files.get('reference')
        input_files = files.getlist('inputs')
        if not reference_file or not input_files:
            raise RuntimeError('Missing reference or input files')
        ref_orig_name = client_meta.get('reference_name') or reference_file.filename
        ref_filename = secure_filename(reference_file.filename)
        ref_path = os.path.join(sdir, ref_filename)
        reference_file.save(ref_path)
        input_paths = []
        input_orig_names = client_meta.get('input_names', [])
        for idx, f in enumerate(input_files):
            fname = secure_filename(f.filename)
            fpath = os.path.join(sdir, fname)
            f.save(fpath)
            input_paths.append(fpath)
        all_to_extract = [ref_path] + input_paths
        extracted_wavs = []
        for p in all_to_extract:
            if p.lower().endswith('.wav'):
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
            sr_ok, sr_msg = check_sample_rates(sr_ref, sr_src)
            valid, flags = preflight_media_check(src_path, src_sig, sr_src)
            if flags:
                robustness_flags[label] = flags
            orig_input_name = input_orig_names[i - 1] if (i - 1) < len(input_orig_names) else os.path.basename(src_path)
            all_signals.append(src_sig)
            all_labels.append(label)
            all_files.append(os.path.basename(orig_input_name))
            all_paths.append(src_path)
        offsets, confidences, feature_dicts = solve_multi_source_sync(
            all_signals, sr_ref, sync_mode=sync_mode, ref_index=0
        )
        results = []
        for idx in range(len(all_signals)):
            label = all_labels[idx]
            fname = all_files[idx]
            offset = float(offsets[idx])
            conf = float(confidences[idx])
            if idx == 0:
                drift_info = {"drift_ms_per_hour": 0.0, "is_significant": False, "reliable_windows": "-", "total_windows": "-", "drift_ci_lower_ms_per_hour": 0.0, "drift_ci_upper_ms_per_hour": 0.0}
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
                "drift_ci_lower": drift_info.get('drift_ci_lower_ms_per_hour', 0.0),
                "drift_ci_upper": drift_info.get('drift_ci_upper_ms_per_hour', 0.0),
                "reliable_windows": f"{drift_info.get('reliable_windows', '-')}/{drift_info.get('total_windows', '-')}",
                "badge": badge,
                "status": status,
                "robustness_flags": flags_for_label,
            })
        report_path = os.path.join(sdir, "sync_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        _update_job(job_id, status="completed", result={"report_path": report_path})
    except Exception as e:
        traceback.print_exc()
        _update_job(job_id, status="failed", error=str(e))
