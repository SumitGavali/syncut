import os
import json
import traceback
import logging
import time
from typing import Optional
from celery.exceptions import Ignore
from synccut.workers.celery_app import celery_app
from synccut.paths import get_sessions_dir
from synccut.media.proxy_gen import generate_proxy
from synccut.media.extract import extract_audio_batch, get_duration, get_video_frame_rate
from synccut.media.mixdown import build_master_mixdown
from synccut.core.sync_engine import solve_multi_source_sync, load_wav
from synccut.core.sync_core import sync_files
from synccut.core.confidence import badge_and_status_from_confidence
from synccut.workers.job_control import (
    JobCancelled,
    check_cancelled,
    clear_partial_audio,
    record_progress,
)

logger = logging.getLogger(__name__)


def _master_audio_url(session_id: str) -> str:
    """Relative URL the browser streams the mixed-down WAV from."""
    return f"/api/session/{session_id}/master_audio"


def _single_camera_fallback(cameras: list, duration: float) -> list:
    if duration <= 0:
        return []
    return [{
        "camera": cameras[0] if cameras else "Camera A",
        "start": 0.0,
        "end": round(duration, 2),
        "confidence": 0.0,
    }]


def _report(task, stage: str, percent: int, status: str):
    """
    Emit PROGRESS only when running inside a real worker request.

    These sub-tasks are also invoked directly (in-process) by full_pipeline_task,
    where there is no request id and ``update_state`` would be a no-op/error.
    """
    if getattr(task.request, "id", None):
        try:
            task.update_state(state="PROGRESS", meta={"stage": stage, "percent": percent, "status": status})
        except Exception:
            logger.debug("update_state failed for stage %s", stage, exc_info=True)


# -------------------------------------------------------------------------
# TASK 1: PROXY GENERATION
# -------------------------------------------------------------------------
@celery_app.task(bind=True)
def generate_proxies_task(self, session_id: str, file_paths: list):
    """Generate 720p proxies for the React UI."""
    _report(self, "proxying", 30, "Starting proxies")

    proxy_dir = os.path.join(get_sessions_dir(), session_id, "proxies")
    results = []

    for idx, path in enumerate(file_paths):
        _report(
            self,
            "proxying",
            int(10 + (idx / max(1, len(file_paths))) * 20),
            f"Generating proxy: {os.path.basename(path)}",
        )
        try:
            proxy_path = generate_proxy(path, proxy_dir)
            results.append({"original": path, "proxy": proxy_path})
        except Exception as e:
            logger.warning(f"Proxy generation failed for {path}: {e}")
            results.append({"original": path, "proxy": path})

    return {"status": "Proxy generation complete", "proxies": results}


# -------------------------------------------------------------------------
# TASK 2: SYNC MATH (GCC-PHAT + Spanning Tree)
# -------------------------------------------------------------------------
@celery_app.task(bind=True)
def run_sync_task(
    self,
    session_id: str,
    payload: dict,
    ref_path: str,
    input_paths: list,
    extracted_wavs: Optional[list] = None,
    progress_callback=None,
    cancel_check=None,
):
    """Align long recordings with bounded FFT windows and prepare the report."""
    externally_controlled = progress_callback is not None or cancel_check is not None
    try:
        job_id = getattr(getattr(self, "request", None), "id", None)
        if progress_callback is None and job_id:
            def progress_callback(current, total, status):
                check_cancelled(job_id)
                record_progress(job_id, current, total, status)
                metadata = {"status": status}
                if current is not None and total is not None:
                    metadata.update({"current": current, "total": total})
                self.update_state(state="PROGRESS", meta=metadata)
        if cancel_check is None and job_id:
            cancel_check = lambda: check_cancelled(job_id)

        sdir = os.path.join(get_sessions_dir(), session_id)
        os.makedirs(sdir, exist_ok=True)
        paths = extracted_wavs or [ref_path] + input_paths
        if len(paths) != len(input_paths) + 1:
            raise ValueError("The number of audio files must match the input sources.")
        labels = ["Reference"] + [
            f"Camera {chr(64 + i)}" if i <= 26 else f"Source {i}"
            for i in range(1, len(paths))
        ]
        files = [os.path.basename(ref_path)] + [os.path.basename(path) for path in input_paths]
        if extracted_wavs is not None:
            files = [os.path.basename(path) for path in [ref_path] + input_paths]

        if os.environ.get("SYNC_ENGINE", "fast").strip().lower() == "legacy":
            wav_paths = extracted_wavs or extract_audio_batch(
                paths, output_dir=os.path.join(sdir, "_audio")
            )
            sample_rate, reference = load_wav(wav_paths[0])
            signals = [reference]
            for wav_path in wav_paths[1:]:
                _, samples = load_wav(wav_path)
                signals.append(samples)
            offsets, confidences, _ = solve_multi_source_sync(
                signals, sample_rate, sync_mode="global", ref_index=0
            )
            cameras = {
                name: {
                    "offset_s": float(offsets[i]),
                    "drift_ppm": 0.0,
                    "link_confidence": float(confidences[i]),
                    "is_master": i == 0,
                    "state": "LOCKED" if i == 0 else "VERIFY",
                }
                for i, name in enumerate(labels)
            }
            sync_rows = []
            audio_paths = wav_paths
            waveform_paths = []
            master_source = labels[0]
            loop_error = 0.0
        else:
            fast_result = sync_files(
                paths,
                cache_dir=os.path.join(sdir, "_sync_audio"),
                names=labels,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )
            cameras = fast_result["cameras"]
            sync_rows = fast_result["rows"]
            audio_paths = fast_result["audio_paths"]
            waveform_paths = fast_result.get("waveform_paths", [])
            master_source = fast_result.get("master_source", labels[0])
            loop_error = fast_result["loop_error_s"]

        results = []
        for idx, label in enumerate(labels):
            camera = cameras[label]
            offset = float(camera["offset_s"])
            drift_ppm = float(camera["drift_ppm"])
            conf = float(camera["link_confidence"])
            drift_ms_per_hour = drift_ppm * 3.6
            badge, status = badge_and_status_from_confidence(conf, drift_ms_per_hour)
            if camera.get("is_master"):
                status = "Good (reference)"
            frame_rate = get_video_frame_rate(paths[idx])
            result_row = {
                "source": label,
                "file": files[idx],
                "offset_s": offset,
                "offset_sec": offset,
                "offset_ms": float(camera.get("offset_ms", offset * 1000.0)),
                "offset_samples": camera.get("offset_samples"),
                "offset_frames": (
                    offset * frame_rate if frame_rate is not None
                    else camera.get("offset_frames")
                ),
                "drift_ppm": drift_ppm,
                "confidence": conf,
                "link_confidence": conf,
                "drift_ms_per_hour": drift_ms_per_hour,
                "psr": camera.get("psr"),
                "window_offsets": camera.get("window_offsets", []),
                "window_std_ms": camera.get("window_std_ms"),
                "state": camera.get("state", "WEAK"),
                "is_master": bool(camera.get("is_master", idx == 0)),
                "warnings": camera.get("warnings", []),
                "frame_rate": frame_rate,
                "duration_sec": get_duration(paths[idx]),
                "badge": badge,
                "status": status,
                "robustness_flags": [],
            }
            if idx < len(waveform_paths):
                result_row["waveform_index"] = idx
            results.append(result_row)

        report_path = os.path.join(sdir, "sync_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "cameras": cameras,
                    "master_source": master_source,
                    "loop_error_s": loop_error,
                    "rows": sync_rows,
                    "results": results,
                    "waveform_files": [os.path.basename(path) for path in waveform_paths],
                },
                f,
                indent=2,
            )

        # Deliverable 2: collapse N stems into one aligned master WAV for the
        # browser waveform. Visual-only, so a failure here must not kill the sync.
        master_audio_url = None
        try:
            mix_path = build_master_mixdown(
                audio_paths,
                [cameras[name]["offset_s"] for name in labels],
                os.path.join(sdir, "master_mix.wav"),
                target_sr=16000,
            )
            if mix_path:
                master_audio_url = _master_audio_url(session_id)
        except Exception:
            logger.warning("Master mixdown failed", exc_info=True)

        return {
            "status": "Sync complete",
            "sync_data": results,
            "rows": sync_rows,
            "cameras": cameras,
            "loop_error_s": loop_error,
            "master_audio_url": master_audio_url,
        }

    except JobCancelled as e:
        if externally_controlled:
            raise
        job_id = getattr(getattr(self, "request", None), "id", None)
        if job_id:
            clear_partial_audio(os.path.join(get_sessions_dir(), session_id, "_sync_audio"))
        self.update_state(state="REVOKED", meta={"status": str(e)})
        raise Ignore()
    except Exception as e:
        traceback.print_exc()
        raise RuntimeError(f"Sync failed: {str(e)}")


# -------------------------------------------------------------------------
# TASK 3: ACTIVE SPEAKER AI CUT
# -------------------------------------------------------------------------
@celery_app.task(bind=True)
def run_ai_cut_task(
    self,
    session_id: str,
    file_paths: list = None,
    progress_callback=None,
    cancel_check=None,
):
    """
    Read the sync report and turn it into an active-speaker rough cut.

    Camera labels come straight from the report so the exported timeline and the
    UI overrides stay in lock-step.
    """
    externally_controlled = progress_callback is not None or cancel_check is not None
    job_id = getattr(getattr(self, "request", None), "id", None)
    if progress_callback is None and job_id:
        def progress_callback(current, total, status):
            check_cancelled(job_id)
            record_progress(job_id, current, total, status)
            metadata = {"status": status}
            if current is not None and total is not None:
                metadata.update({"current": current, "total": total})
            self.update_state(state="PROGRESS", meta=metadata)
    if cancel_check is None and job_id:
        cancel_check = lambda: check_cancelled(job_id)
    if progress_callback:
        progress_callback(None, None, "Preparing rough-cut analysis")

    sdir = os.path.join(get_sessions_dir(), session_id)
    report_path = os.path.join(sdir, "sync_report.json")
    if not os.path.exists(report_path):
        raise RuntimeError("Cannot run AI cut: sync_report.json is missing.")

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)
    results = report.get("results", []) if isinstance(report, dict) else report
    cameras = report.get("cameras", {}) if isinstance(report, dict) else {}

    # Resolve each report row to an absolute media path (report stores basenames).
    file_paths = file_paths or []
    sources_data = {}
    for row in results:
        name = row.get("file")
        media_path = next((p for p in file_paths if os.path.basename(p) == name), None)
        if media_path is None and name:
            candidate = os.path.join(sdir, name)
            if os.path.exists(candidate):
                media_path = candidate
        if media_path:
            sources_data[row["source"]] = {
                "file": media_path,
                "offset_sec": float(
                    cameras.get(row["source"], {}).get(
                        "offset_s", row.get("offset_s", row.get("offset_sec", 0.0))
                    )
                ),
            }

    segments = []
    try:
        if sources_data:
            from synccut.ai.rough_cut import generate_active_speaker_roughcut
            last_progress_at = [0.0]
            last_percent = [95.0]
            source_names = list(sources_data)

            def report_frame(current, total, status):
                if cancel_check:
                    cancel_check()
                now = time.monotonic()
                source_index = next(
                    (
                        index
                        for index, name in enumerate(source_names)
                        if os.path.basename(sources_data[name]["file"]) in status
                    ),
                    0,
                )
                fraction = (
                    min(1.0, max(0.0, current / total))
                    if current is not None and total
                    else 0.0
                )
                current_percent = 95.0 + 4.0 * (
                    source_index + fraction
                ) / max(1, len(source_names))
                if (
                    progress_callback
                    and current_percent > last_percent[0]
                    and now - last_progress_at[0] >= 1.0
                ):
                    progress_callback(
                        current_percent,
                        100.0,
                        f"AI rough cut: {status}",
                    )
                    last_percent[0] = current_percent
                    last_progress_at[0] = now

            segments = generate_active_speaker_roughcut(
                sources_data,
                cancel_check=cancel_check,
                progress_callback=report_frame,
            ) or []
    except JobCancelled as e:
        if externally_controlled:
            raise
        if job_id:
            clear_partial_audio(os.path.join(get_sessions_dir(), session_id, "_sync_audio"))
        self.update_state(state="REVOKED", meta={"status": str(e)})
        raise Ignore()
    except Exception:
        logger.warning("Active-speaker rough cut failed; using a single-camera fallback", exc_info=True)

    if not segments:
        # If speaker detection yields no cuts, keep the reference angle rather
        # than inventing alternating camera decisions.
        cameras = [row["source"] for row in results] or ["Camera A"]
        total_dur = 60.0
        mix_path = os.path.join(sdir, "master_mix.wav")
        if os.path.exists(mix_path):
            try:
                mix_sr, mix_sig = load_wav(mix_path)
                total_dur = len(mix_sig) / float(mix_sr or 16000)
            except Exception:
                pass

        segments = _single_camera_fallback(cameras, total_dur)

    switches_path = os.path.join(sdir, "switches.json")
    with open(switches_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, indent=2)

    from synccut.api.routes import SESSIONS

    session_state = SESSIONS.setdefault(
        session_id,
        {
            "session_id": session_id,
            "media_dir": sdir,
            "report_json_path": report_path,
            "report_results": results,
            "all_signals": [],
            "fs": 16000,
        },
    )
    session_state["last_switches"] = segments
    session_state["segments"] = segments
    session_state.setdefault("last_switches_media_dir", session_state.get("media_dir", sdir))

    return {"status": "AI cut complete", "segments": segments}


# -------------------------------------------------------------------------
# TASK 4: MASTER ORCHESTRATION (Deliverable 3)
# -------------------------------------------------------------------------
@celery_app.task(bind=True)
def full_pipeline_task(self, session_id: str, file_paths: list):
    """
    Run audio extraction → sync math → AI cut behind one job id so
    the frontend only has to poll a single progress endpoint.
    """
    try:
        sdir = os.path.join(get_sessions_dir(), session_id)
        os.makedirs(sdir, exist_ok=True)

        if not file_paths:
            raise ValueError("At least one media file is required.")

        ref_path = file_paths[0]
        input_paths = file_paths[1:]
        job_id = getattr(getattr(self, "request", None), "id", None)

        def progress(current, total, status):
            if job_id:
                check_cancelled(job_id)
                record_progress(job_id, current, total, status)
                metadata = {"status": status}
                if current is not None and total is not None:
                    metadata.update({"current": current, "total": total})
                self.update_state(state="PROGRESS", meta=metadata)

        progress(None, None, "Preparing audio-only synchronization")
        sync_result = run_sync_task(
            session_id,
            {},
            ref_path,
            input_paths,
            progress_callback=progress,
            cancel_check=(lambda: check_cancelled(job_id)) if job_id else None,
        )
        master_audio_url = sync_result.get("master_audio_url")
        if job_id:
            check_cancelled(job_id)
        progress(None, None, "Detecting rough-cut segments")
        cut_result = run_ai_cut_task(
            session_id,
            file_paths,
            progress_callback=progress,
            cancel_check=(lambda: check_cancelled(job_id)) if job_id else None,
        )

        progress(100.0, 100.0, "Pipeline complete")
        self.update_state(state="SUCCESS", meta={"status": "Ready for Review"})
        return {
            "status": "Ready for Review",
            "sync_data": sync_result.get("sync_data", []),
            "rows": sync_result.get("rows", []),
            "cameras": sync_result.get("cameras", {}),
            "master_source": sync_result.get("master_source"),
            "loop_error_s": sync_result.get("loop_error_s", 0.0),
            "segments": cut_result.get("segments", []),
            "master_audio_url": master_audio_url,
        }

    except JobCancelled as e:
        job_id = getattr(getattr(self, "request", None), "id", None)
        if job_id:
            clear_partial_audio(os.path.join(get_sessions_dir(), session_id, "_sync_audio"))
        self.update_state(state="REVOKED", meta={"status": str(e)})
        raise Ignore()
    except Exception as e:
        traceback.print_exc()
        raise RuntimeError(f"Pipeline error: {str(e)}")
