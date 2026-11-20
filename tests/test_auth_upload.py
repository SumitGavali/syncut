import os
import json
from io import BytesIO
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

import pytest

from synccut.api import db
from synccut.api.factory import create_app


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "synccut-test.db")
    db.init_db()
    app = create_app(
        {
            "TESTING": True,
            "UPLOAD_ROOT": str(tmp_path / "uploads"),
            "SECRET_KEY": "test-secret-key",
        }
    )
    return app.test_client()


def register_user(client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "editor@example.test",
            "name": "Editor",
            "password": "secure-password",
        },
    )
    assert response.status_code == 201
    return response.get_json()["token"]


def test_login_does_not_create_unknown_users(api_client):
    login_response = api_client.post(
        "/api/auth/login",
        json={"email": "new@example.test", "password": "secure-password"},
    )
    assert login_response.status_code == 401

    register_response = api_client.post(
        "/api/auth/register",
        json={
            "email": "new@example.test",
            "name": "New Editor",
            "password": "secure-password",
        },
    )
    assert register_response.status_code == 201


def test_login_rejects_malformed_credentials(api_client):
    assert api_client.post("/api/auth/login", json={"email": [], "password": "valid-password"}).status_code == 400
    assert api_client.post("/api/auth/login", json=["not", "an", "object"]).status_code == 400
    assert api_client.post("/api/auth/login", json={"email": "new@example.test", "password": "wrong"}).status_code == 401


def test_password_reset_sends_single_use_link_and_replaces_password(
    api_client, monkeypatch
):
    token = register_user(api_client)
    sent_emails = []
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "no-reply@example.test")
    monkeypatch.setattr(
        "synccut.api.auth.send_password_reset_email",
        lambda email, link, *, send_email: sent_emails.append((email, link))
        if send_email else None,
    )

    response = api_client.post(
        "/api/auth/forgot-password",
        json={"email": "EDITOR@example.test"},
    )
    unknown_response = api_client.post(
        "/api/auth/forgot-password",
        json={"email": "missing@example.test"},
    )
    assert response.status_code == 202
    assert response.get_json() == unknown_response.get_json()
    assert len(sent_emails) == 1
    assert sent_emails[0][0] == "EDITOR@example.test"

    query = urlsplit(sent_emails[0][1]).fragment.split("?", 1)[1]
    reset_token = parse_qs(query)["token"][0]
    reset_response = api_client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "password": "new-secure-password"},
    )
    assert reset_response.status_code == 200
    assert api_client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "password": "another-password"},
    ).status_code == 400
    assert api_client.post(
        "/api/auth/login",
        json={"email": "editor@example.test", "password": "secure-password"},
    ).status_code == 401
    new_login = api_client.post(
        "/api/auth/login",
        json={"email": "editor@example.test", "password": "new-secure-password"},
    )
    assert new_login.status_code == 200
    assert db.get_user_by_token(token) is None


def test_password_reset_reports_missing_smtp_configuration(api_client, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    response = api_client.post(
        "/api/auth/forgot-password",
        json={"email": "editor@example.test"},
    )
    assert response.status_code == 503
    assert "SMTP_HOST" in response.get_json()["error"]


def test_google_auth_requires_client_id_and_links_verified_identity(api_client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    response = api_client.post("/api/auth/google/start")
    assert response.status_code == 503
    assert "GOOGLE_CLIENT_ID" in response.get_json()["error"]

    local_user = db.create_user("google@example.test", "Local User", "secure-password")
    linked_user = db.authenticate_google_user(
        "google-subject-1", "GOOGLE@example.test", "Google User"
    )
    assert linked_user is not None
    assert linked_user["id"] == local_user["id"]
    assert db.authenticate_google_user(
        "different-google-subject", "google@example.test", "Other User"
    ) is None
    assert db.authenticate_user("google@example.test", "secure-password") is not None


def test_google_oauth_uses_system_browser_callback(api_client, monkeypatch):
    from synccut.api import auth as auth_helpers

    opened_urls = []
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "desktop-client-id")
    monkeypatch.setattr(
        auth_helpers.webbrowser,
        "open",
        lambda url, new: opened_urls.append(url) or True,
    )
    monkeypatch.setattr(
        auth_helpers,
        "_verify_google_response",
        lambda code, verifier, redirect_uri, client_id: {
            "status": "complete",
            "user": {"id": "google-user", "email": "google@example.test"},
            "token": "google-auth-token",
        },
    )

    start = api_client.post("/api/auth/google/start")
    assert start.status_code == 200
    assert start.get_json()["flow_id"]
    oauth_url = urlsplit(opened_urls[0])
    oauth_query = parse_qs(oauth_url.query)
    callback_url = oauth_query["redirect_uri"][0]
    callback_query = urlencode({"code": "test-code", "state": oauth_query["state"][0]})
    with urlopen(f"{callback_url}?{callback_query}", timeout=5) as callback:
        assert callback.status == 200

    for _ in range(20):
        result = api_client.get(
            "/api/auth/google/poll",
            query_string={"flow_id": start.get_json()["flow_id"]},
        )
        if result.get_json()["status"] != "pending":
            break
        time.sleep(0.05)
    assert result.status_code == 200
    assert result.get_json()["status"] == "complete"
    assert result.get_json()["token"] == "google-auth-token"


def test_legacy_dashboard_redirects_to_login_until_authenticated(api_client):
    assert api_client.get("/app").status_code == 302
    assert api_client.get("/login").status_code == 200

    db.create_user("browser@example.test", "Browser User", "secure-password")
    login_response = api_client.post(
        "/login",
        data={"email": "browser@example.test", "password": "secure-password"},
    )
    assert login_response.status_code == 302
    assert api_client.get("/app").status_code == 200


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/projects", "get"),
        ("/api/projects", "post"),
        ("/api/upload", "post"),
        ("/api/sync", "post"),
        ("/api/sync_async", "post"),
    ],
)
def test_private_project_and_upload_routes_require_auth(api_client, path, method):
    response = getattr(api_client, method)(path)
    assert response.status_code == 401


def test_upload_requires_two_to_eight_supported_files(api_client):
    token = register_user(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    too_few = api_client.post(
        "/api/upload",
        data={"session_id": "test-session", "files": (BytesIO(b"video"), "clip.mp4")},
        headers=headers,
    )
    assert too_few.status_code == 400

    unsupported = api_client.post(
        "/api/upload",
        data={
            "session_id": "test-session",
            "files": [
                (BytesIO(b"video"), "first.mp4"),
                (BytesIO(b"document"), "notes.txt"),
            ],
        },
        headers=headers,
    )
    assert unsupported.status_code == 415


def test_authenticated_upload_saves_supported_files_and_starts_pipeline(
    api_client, tmp_path, monkeypatch
):
    token = register_user(api_client)
    headers = {"Authorization": f"Bearer {token}"}
    from synccut.api import routes
    from synccut.core import quota
    started_jobs = []
    monkeypatch.setattr(quota, "check_video_duration", lambda _path: 60.0)

    def run_job(job_id, session_id, file_paths):
        started_jobs.append((job_id, session_id, file_paths))

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target
            assert daemon is True

        def start(self):
            self.target()

    monkeypatch.setattr(routes, "_run_local_full_pipeline_job", run_job)
    monkeypatch.setattr(routes.threading, "Thread", ImmediateThread)

    response = api_client.post(
        "/api/upload",
        data={
            "session_id": "test-session",
            "files": [
                (BytesIO(b"reference video"), "same-name.mp4"),
                (BytesIO(b"camera video"), "same-name.mp4"),
            ],
        },
        headers=headers,
    )

    assert response.status_code == 202
    job_id = response.get_json()["job_id"]
    assert job_id.startswith("pipeline-")
    assert response.get_json()["file_count"] == 2
    assert started_jobs == [
        (
            job_id,
            "test-session",
            [
                str(tmp_path / "uploads" / "test-session" / "01_same-name.mp4"),
                str(tmp_path / "uploads" / "test-session" / "02_same-name.mp4"),
            ],
        )
    ]
    session_dir = tmp_path / "uploads" / "test-session"
    assert (session_dir / "01_same-name.mp4").read_bytes() == b"reference video"
    assert (session_dir / "02_same-name.mp4").read_bytes() == b"camera video"


def test_rejected_upload_preserves_existing_session_media(api_client, tmp_path, monkeypatch):
    token = register_user(api_client)
    owner_id = db.get_user_by_token(token)["id"]
    session_dir = tmp_path / "uploads" / "existing-session"
    session_dir.mkdir(parents=True)
    (session_dir / ".owner.json").write_text(json.dumps({"user_id": owner_id}), encoding="utf-8")
    (session_dir / "01_same-name.mp4").write_bytes(b"existing reference")
    (session_dir / "02_same-name.mp4").write_bytes(b"existing camera")

    from synccut.core import quota
    monkeypatch.setattr(quota, "check_video_duration", lambda _path: 601.0)
    response = api_client.post(
        "/api/upload",
        data={
            "session_id": "existing-session",
            "files": [
                (BytesIO(b"new reference"), "same-name.mp4"),
                (BytesIO(b"new camera"), "same-name.mp4"),
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert (session_dir / "01_same-name.mp4").read_bytes() == b"existing reference"
    assert (session_dir / "02_same-name.mp4").read_bytes() == b"existing camera"


def test_upload_rejects_traversal_and_another_accounts_session(api_client):
    token = register_user(api_client)
    headers = {"Authorization": f"Bearer {token}"}
    traversal = api_client.post(
        "/api/upload",
        data={
            "session_id": "../outside",
            "files": [
                (BytesIO(b"reference video"), "one.mp4"),
                (BytesIO(b"camera video"), "two.mp4"),
            ],
        },
        headers=headers,
    )
    assert traversal.status_code == 400

    session_dir = os.path.join(api_client.application.config["UPLOAD_ROOT"], "owned-session")
    os.makedirs(session_dir)
    with open(os.path.join(session_dir, ".owner.json"), "w", encoding="utf-8") as owner_file:
        owner_file.write('{"user_id":"some-other-user"}')

    foreign_session = api_client.post(
        "/api/upload",
        data={
            "session_id": "owned-session",
            "files": [
                (BytesIO(b"reference video"), "one.mp4"),
                (BytesIO(b"camera video"), "two.mp4"),
            ],
        },
        headers=headers,
    )
    assert foreign_session.status_code == 403


def test_project_json_is_persisted_and_private(api_client, tmp_path):
    token = register_user(api_client)
    owner_id = db.get_user_by_token(token)["id"]
    session_dir = tmp_path / "uploads" / "project-session"
    session_dir.mkdir(parents=True)
    (session_dir / ".owner.json").write_text(json.dumps({"user_id": owner_id}), encoding="utf-8")
    project = {
        "version": 1,
        "fps": 25,
        "master_audio": None,
        "master_camera": "Reference",
        "cameras": [{"source": "Reference", "offset_s": 0.0}],
        "program": [{"camera": "Reference", "start": 0, "end": 10, "source": "manual"}],
        "settings": {"snapping": True, "overlayCamera": None},
        "history": [],
    }

    headers = {"Authorization": f"Bearer {token}"}
    saved = api_client.put(
        "/api/session/project-session/project",
        json=project,
        headers=headers,
    )
    assert saved.status_code == 200
    assert json.loads((session_dir / "project.json").read_text(encoding="utf-8")) == project
    loaded = api_client.get("/api/session/project-session/project", headers=headers)
    assert loaded.status_code == 200
    assert loaded.get_json()["project"] == project

    other_token = db.create_user("other@example.test", "Other", "secure-password")["token"]
    denied = api_client.get(
        "/api/session/project-session/project",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert denied.status_code == 403


def test_camera_waveform_and_media_routes_require_owned_session(api_client, tmp_path):
    token = register_user(api_client)
    owner_id = db.get_user_by_token(token)["id"]
    session_dir = tmp_path / "uploads" / "media-session"
    cache_dir = session_dir / "_sync_audio"
    cache_dir.mkdir(parents=True)
    (session_dir / ".owner.json").write_text(json.dumps({"user_id": owner_id}), encoding="utf-8")
    (cache_dir / "cam.waveform").write_bytes(bytes([0, 64, 255]))
    (session_dir / "01_camera.mp4").write_bytes(b"video")
    (session_dir / "master_mix.wav").write_bytes(b"wave")
    (session_dir / "sync_report.json").write_text(
        json.dumps({
            "waveform_files": ["cam.waveform"],
            "results": [{"file": "01_camera.mp4"}],
        }),
        encoding="utf-8",
    )

    headers = {"Authorization": f"Bearer {token}"}
    waveform = api_client.get("/api/session/media-session/waveform/0", headers=headers)
    assert waveform.status_code == 200
    assert waveform.data == bytes([0, 64, 255])
    assert waveform.headers["X-Waveform-Rate"] == "100"
    master_audio = api_client.get("/api/session/media-session/master_audio", headers=headers)
    assert master_audio.status_code == 200
    assert master_audio.data == b"wave"
    assert api_client.application.test_client().get(
        "/api/session/media-session/master_audio"
    ).status_code == 401

    media = api_client.get("/api/session/media-session/media/0", headers=headers)
    assert media.status_code == 200
    assert media.data == b"video"


def test_camera_thumbnail_is_authenticated_generated_and_cached(api_client, tmp_path, monkeypatch):
    from synccut.api import routes

    token = register_user(api_client)
    owner_id = db.get_user_by_token(token)["id"]
    session_dir = tmp_path / "uploads" / "thumbnail-session"
    session_dir.mkdir(parents=True)
    (session_dir / ".owner.json").write_text(json.dumps({"user_id": owner_id}), encoding="utf-8")
    (session_dir / "01_camera.mp4").write_bytes(b"video")
    (session_dir / "sync_report.json").write_text(
        json.dumps({"results": [{"file": "01_camera.mp4", "duration_sec": 60.0}]}),
        encoding="utf-8",
    )
    commands = []

    def fake_ffmpeg(command, **_kwargs):
        commands.append(command)
        with open(command[-1], "wb") as thumbnail:
            thumbnail.write(b"\xff\xd8fake-jpeg")

    monkeypatch.setattr(routes, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(routes.subprocess, "run", fake_ffmpeg)

    anonymous = api_client.application.test_client()
    unauthorized = anonymous.get("/api/session/thumbnail-session/thumbnail/0?time=15")
    assert unauthorized.status_code == 401

    headers = {"Authorization": f"Bearer {token}"}
    first = api_client.get("/api/session/thumbnail-session/thumbnail/0?time=15", headers=headers)
    second = api_client.get("/api/session/thumbnail-session/thumbnail/0?time=19", headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.mimetype == "image/jpeg"
    assert first.data.startswith(b"\xff\xd8")
    assert len(commands) == 1
    assert commands[0][commands[0].index("-ss") + 1] == "20.000"
