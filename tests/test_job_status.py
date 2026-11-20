from flask import Flask

from synccut.api import routes


def _client():
    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    return app.test_client()


def test_job_status_returns_unknown_for_untracked_job(monkeypatch):
    monkeypatch.setattr(routes, "LOCAL_JOBS", {})

    response = _client().get("/api/job/status?job_id=job-1")

    assert response.status_code == 200
    assert response.get_json() == {"status": "UNKNOWN"}


def test_local_job_status_returns_success_result(monkeypatch):
    result = {
        "session_id": "session-1",
        "sync_data": [{"source": "Reference"}],
        "segments": [{"start": 0, "end": 5, "camera": "Reference"}],
    }
    monkeypatch.setattr(
        routes,
        "LOCAL_JOBS",
        {"job-2": {"status": "SUCCESS", "result": result}},
    )

    response = _client().get("/api/job/status?job_id=job-2")

    assert response.get_json() == {
        "job_id": "job-2",
        "status": "SUCCESS",
        "result": result,
    }


def test_local_job_stall_is_reported_without_internal_timestamp(monkeypatch):
    import time

    monkeypatch.setattr(
        routes,
        "LOCAL_JOBS",
        {
            "job-3": {
                "status": "PROGRESS",
                "metadata": {
                    "status": "Working",
                    "changed_at": time.time() - 91,
                },
            }
        },
    )

    response = _client().get("/api/job/status?job_id=job-3")

    assert response.get_json() == {
        "job_id": "job-3",
        "status": "STALLED",
        "metadata": {"status": "Working"},
    }


def test_storing_local_progress_does_not_require_http_request_context(monkeypatch):
    monkeypatch.setattr(
        routes,
        "LOCAL_JOBS",
        {"job-4": {"status": "PENDING"}},
    )

    routes._store_local_progress("job-4", None, None, "Decoding camera audio")

    assert routes.LOCAL_JOBS["job-4"]["status"] == "PROGRESS"
    assert routes.LOCAL_JOBS["job-4"]["metadata"]["status"] == "Decoding camera audio"


def test_local_pipeline_helpers_run_without_celery_task_context(monkeypatch, tmp_path):
    from synccut.ai import rough_cut
    from synccut.workers import tasks

    def fake_sync_files(paths, **kwargs):
        kwargs["progress_callback"](1, 1, "Audio aligned")
        return {
            "cameras": {
                "Reference": {
                    "offset_s": 0.0,
                    "drift_ppm": 0.0,
                    "link_confidence": 1.0,
                    "is_master": True,
                },
                "Camera A": {
                    "offset_s": 0.25,
                    "drift_ppm": 0.0,
                    "link_confidence": 0.9,
                    "is_master": False,
                },
            },
            "rows": [],
            "audio_paths": [],
            "waveform_paths": [],
            "loop_error_s": 0.0,
        }

    monkeypatch.setattr(tasks, "get_sessions_dir", lambda: str(tmp_path))
    monkeypatch.setattr(tasks, "sync_files", fake_sync_files)
    monkeypatch.setattr(tasks, "get_video_frame_rate", lambda _path: None)
    monkeypatch.setattr(tasks, "get_duration", lambda _path: 10.0)
    monkeypatch.setattr(tasks, "build_master_mixdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        rough_cut,
        "generate_active_speaker_roughcut",
        lambda *args, **kwargs: [
            {"camera": "Camera A", "start": 0.0, "end": 5.0}
        ],
    )
    progress = []
    callback = lambda current, total, status: progress.append(status)

    sync_result = tasks.run_sync_task(
        "local-session",
        {},
        "reference.mp4",
        ["camera-a.mp4"],
        progress_callback=callback,
        cancel_check=lambda: None,
    )
    cut_result = tasks.run_ai_cut_task(
        "local-session",
        ["reference.mp4", "camera-a.mp4"],
        progress_callback=callback,
        cancel_check=lambda: None,
    )

    assert sync_result["sync_data"][1]["offset_s"] == 0.25
    assert cut_result["segments"] == [
        {"camera": "Camera A", "start": 0.0, "end": 5.0}
    ]
    assert "Audio aligned" in progress


def test_rough_cut_uses_synced_camera_offset_without_cached_audio(
    monkeypatch, tmp_path
):
    session_id = "session-rough-cut"
    reference = tmp_path / "reference.mp4"
    camera = tmp_path / "camera_a.mp4"
    reference.touch()
    camera.touch()
    report_path = tmp_path / "sync_report.json"
    report_path.write_text(
        '{"cameras":{"Camera A":{"offset_s":1.234}},'
        '"results":[{"source":"Reference","file":"reference.mp4",'
        '"offset_s":0.0,"offset_sec":0.0},{"source":"Camera A",'
        '"file":"camera_a.mp4","offset_s":99.0,"offset_sec":99.0}]}',
        encoding="utf-8",
    )
    state = {
        "report_json_path": str(report_path),
        "media_dir": str(tmp_path),
        "reference_path": str(reference),
        "input_paths": [str(camera)],
        "report_results": [
            {"source": "Reference", "file": "reference.mp4", "offset_s": 0.0},
            {"source": "Camera A", "file": "camera_a.mp4", "offset_s": 99.0},
        ],
        "fs": 16000,
    }
    received_sources = {}
    monkeypatch.setattr(routes, "SESSIONS", {session_id: state})
    monkeypatch.setattr(routes, "session_dir", lambda _: str(tmp_path))

    def fake_rough_cut(sources_data, fs):
        received_sources.update(sources_data)
        return [{"camera": "Camera A", "start": 0, "end": 5}]

    monkeypatch.setattr(routes, "generate_active_speaker_roughcut", fake_rough_cut)

    response = _client().post(
        "/api/switches", json={"session_id": session_id}
    )

    assert response.status_code == 200
    assert received_sources["Camera A"] == {
        "file": str(camera),
        "offset_sec": 1.234,
    }
    assert state["last_switches"][0]["camera"] == "Camera A"
