from flask import Flask

from synccut.api import routes


def _client():
    app = Flask(__name__)
    app.register_blueprint(routes.bp)
    return app.test_client()


def test_job_status_returns_unknown_when_backend_is_unavailable(monkeypatch):
    class UnavailableRedis:
        def ping(self):
            raise ConnectionError("Redis unavailable")

    monkeypatch.setattr(routes, "redis_client", UnavailableRedis)

    response = _client().get("/api/job/status?job_id=job-1")

    assert response.status_code == 200
    assert response.get_json() == {"status": "UNKNOWN"}


def test_celery_success_populates_api_session_state(monkeypatch, tmp_path):
    session_state = {}
    result = {
        "session_id": "session-1",
        "sync_data": [{"source": "Reference"}],
        "segments": [{"start": 0, "end": 5, "camera": "Reference"}],
    }

    class AvailableRedis:
        def ping(self):
            return True

    class SuccessfulTask:
        def __init__(self):
            self.state = "SUCCESS"
            self.result = result

    monkeypatch.setattr(routes, "LOCAL_JOBS", {})
    monkeypatch.setattr(routes, "redis_client", AvailableRedis)
    monkeypatch.setattr(
        routes, "AsyncResult", lambda job_id, app: SuccessfulTask()
    )
    monkeypatch.setattr(routes, "get_session", lambda session_id: session_state)
    monkeypatch.setattr(routes, "session_dir", lambda session_id: str(tmp_path))

    response = _client().get("/api/job/status?job_id=job-2")

    assert response.get_json()["result"] == result
    assert session_state["report_results"] == result["sync_data"]
    assert session_state["segments"] == result["segments"]
    assert session_state["last_switches"] == result["segments"]
    assert session_state["report_json_path"] == str(tmp_path / "sync_report.json")


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
