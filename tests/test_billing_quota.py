from datetime import datetime, timezone
from io import BytesIO
import sqlite3
from types import SimpleNamespace

import pytest

from synccut.api import db
from synccut.api.factory import create_app
from synccut.core import quota


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "synccut-billing-test.db")
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
            "email": "billing@example.test",
            "name": "Billing User",
            "password": "secure-password",
        },
    )
    assert response.status_code == 201
    return response.get_json()["token"]


def test_checkout_requires_configuration(api_client, monkeypatch):
    token = register_user(api_client)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_PRO_PRICE_ID", raising=False)

    response = api_client.post(
        "/api/billing/checkout",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503


def test_legacy_sqlite_accounts_migrate_to_sqlalchemy(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "_DB_PATH", database_path)
    salt, password_hash = db.hash_password("secure-password")
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            password_hash TEXT NOT NULL, salt TEXT NOT NULL, token TEXT,
            plan TEXT DEFAULT 'Pro Plan', created_at TEXT NOT NULL
        );
        CREATE TABLE projects (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL,
            description TEXT, status TEXT NOT NULL, camera_count INTEGER DEFAULT 2,
            duration TEXT DEFAULT '00:00:00', thumbnail_url TEXT,
            confidence_score REAL DEFAULT 1.0, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "legacy-user",
            "legacy@example.test",
            "Legacy User",
            password_hash,
            salt,
            "legacy-token",
            "Pro Plan",
            "2025-01-01T00:00:00",
        ),
    )
    connection.execute(
        "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "legacy-project",
            "legacy-user",
            "Legacy Project",
            "",
            "Draft",
            2,
            "00:00:00",
            "",
            1.0,
            "Jan 01, 2025",
            "Jan 01, 2025",
        ),
    )
    connection.commit()
    connection.close()

    db.init_db()

    user = db.authenticate_user("legacy@example.test", "secure-password")
    assert user is not None
    assert user["tier"] == "free"
    project = db.get_user_projects("legacy-user")[0]
    assert project["id"] == "legacy-project"
    assert project["session_id"] == "legacy-project"


def test_checkout_creates_pro_subscription_session(api_client, monkeypatch):
    from synccut.api import billing

    token = register_user(api_client)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_pro_monthly")
    requests = []

    def create_session(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(url="https://checkout.stripe.test/session")

    monkeypatch.setattr(billing.stripe.checkout.Session, "create", create_session)
    response = api_client.post(
        "/api/billing/checkout",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.get_json()["checkout_url"] == "https://checkout.stripe.test/session"
    assert requests[0]["mode"] == "subscription"
    assert requests[0]["line_items"] == [{"price": "price_pro_monthly", "quantity": 1}]
    assert requests[0]["subscription_data"]["metadata"]["tier"] == "pro"


def test_webhook_activates_and_cancels_subscription(api_client, monkeypatch):
    from synccut.api import billing

    token = register_user(api_client)
    user_id = db.get_user_by_token(token)["id"]
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_key")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_key")
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "subscription",
                "client_reference_id": user_id,
                "subscription": "sub_test",
                "customer": "cus_test",
            }
        },
    }
    expires_at = 1_800_000_000
    monkeypatch.setattr(
        billing.stripe.Webhook,
        "construct_event",
        lambda *_args, **_kwargs: event,
    )
    monkeypatch.setattr(
        billing.stripe.Subscription,
        "retrieve",
        lambda _subscription_id: SimpleNamespace(
            status="active",
            current_period_end=expires_at,
        ),
    )

    completed = api_client.post(
        "/api/billing/webhook",
        data=b"checkout event",
        headers={"Stripe-Signature": "valid-signature"},
    )

    assert completed.status_code == 200
    assert db.get_user_tier(user_id) == "pro"
    assert db.get_subscription_info(user_id)["expires_at"] == datetime.fromtimestamp(
        expires_at, tz=timezone.utc
    ).isoformat()

    event["type"] = "customer.subscription.deleted"
    event["data"]["object"] = {"id": "sub_test", "customer": "cus_test"}
    deleted = api_client.post(
        "/api/billing/webhook",
        data=b"subscription deleted event",
        headers={"Stripe-Signature": "valid-signature"},
    )

    assert deleted.status_code == 200
    assert db.get_user_tier(user_id) == "free"


def test_quota_enforces_camera_and_duration_limits(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "synccut-quota-test.db")
    db.init_db()
    user = db.create_user("quota@example.test", "Quota User", "secure-password")
    camera_files = [tmp_path / f"camera-{index}.mp4" for index in range(3)]
    with pytest.raises(PermissionError, match="2 cameras"):
        quota.enforce_limits(user["id"], camera_files)

    monkeypatch.setattr(quota, "check_video_duration", lambda _path: 601.0)
    with pytest.raises(PermissionError, match="10 minutes"):
        quota.enforce_limits(user["id"], camera_files[:2])


def test_video_duration_uses_ffprobe(monkeypatch):
    command = []

    def fake_run(args, **kwargs):
        command.extend(args)
        assert kwargs["check"] is True
        return SimpleNamespace(stdout="600.5\n")

    monkeypatch.setattr(quota, "get_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(quota.subprocess, "run", fake_run)

    assert quota.check_video_duration("camera.mp4") == 600.5
    assert command[0] == "ffprobe"
    assert command[-1] == "camera.mp4"


def test_free_tier_restricts_ai_cuts_and_premium_exports(api_client):
    token = register_user(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    assert api_client.post("/api/switches", json={}, headers=headers).status_code == 403
    fcpxml = api_client.post(
        "/api/export/timeline",
        json={"session_id": "unprocessed-session", "format": "fcpxml"},
        headers=headers,
    )
    assert fcpxml.status_code == 403
    export_4k = api_client.post(
        "/api/export/timeline",
        json={"session_id": "unprocessed-session", "format": "pdf", "resolution": "4k"},
        headers=headers,
    )
    assert export_4k.status_code == 403


def test_free_user_cannot_upload_more_than_two_cameras(api_client):
    token = register_user(api_client)
    response = api_client.post(
        "/api/upload",
        data={
            "session_id": "free-three-camera-session",
            "files": [
                (BytesIO(b"one"), "one.mp4"),
                (BytesIO(b"two"), "two.mp4"),
                (BytesIO(b"three"), "three.mp4"),
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 403
    assert "2 cameras" in response.get_json()["error"]
