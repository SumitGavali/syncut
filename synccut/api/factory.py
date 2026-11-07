"""
Flask application factory for SyncCut.

Usage:
    from synccut.api import create_app
    app = create_app()

Gunicorn:
    gunicorn \"synccut.api.factory:create_app()\" ...
    # or root shim:  gunicorn app:app
"""
from __future__ import annotations

import os
import secrets
import socket
from pathlib import Path

from flask import Flask
from flask_cors import CORS

from synccut.api.db import init_db

from synccut.api.billing import billing_bp
from synccut.api.routes import bp as api_bp
from synccut.paths import (
    cleanup_old_temp_files,
    get_base_dir,
    get_sessions_dir,
    get_user_data_dir,
)


# Default origins for local development
DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
]


def _get_secret_key() -> str:
    configured = os.environ.get("SYNCCUT_SECRET_KEY")
    if configured:
        return configured
    secret_path = get_user_data_dir() / ".flask_secret_key"
    try:
        with secret_path.open("x", encoding="utf-8") as secret_file:
            secret = secrets.token_hex(32)
            secret_file.write(secret)
            return secret
    except FileExistsError:
        return secret_path.read_text(encoding="utf-8").strip()


def find_free_port(preferred: int = 5000) -> int:
    """Find a free port starting from preferred, or let OS pick one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def create_app(config: dict | None = None) -> Flask:
    """
    Build and configure the Flask application.

    Args:
        config: Optional overrides merged into ``app.config``.
    """
    package_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )

    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB
    app.config["SECRET_KEY"] = _get_secret_key()
    app.config["STUDIO_URL"] = os.environ.get("SYNCCUT_STUDIO_URL", "http://localhost:5173")
    app.config["APP_ROOT"] = str(get_base_dir())
    app.config["UPLOAD_ROOT"] = str(get_sessions_dir())
    if config:
        app.config.update(config)

    # --- DYNAMIC CORS CONFIGURATION ---
    # Read the allowed origins from an environment variable. If not set, use the local dev defaults.
    # This allows you to whitelist your live Vercel URL without modifying the source code.
    env_origins = os.environ.get("CORS_ORIGINS", "")
    if env_origins:
        cors_origins = [origin.strip() for origin in env_origins.split(",") if origin.strip()]
    else:
        cors_origins = list(DEFAULT_CORS_ORIGINS)

    # Also add the STUDIO_URL if it's not already in the list
    studio_origin = app.config["STUDIO_URL"].rstrip("/")
    if studio_origin and studio_origin not in cors_origins:
        cors_origins.append(studio_origin)

    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": cors_origins,
                "supports_credentials": True,  # Allows cookies and Authorization headers
                "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type", "Authorization"],
            }
        },
    )

    cleanup_old_temp_files(max_age_hours=24.0)
    app.register_blueprint(api_bp)
    app.register_blueprint(billing_bp)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Eager init for local/desktop and single-worker gunicorn.
    # Celery workers will replace job_manager.start_executor() later.
    if not app.config.get("TESTING"):
        init_db()

    return app