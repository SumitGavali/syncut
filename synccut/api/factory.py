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
import socket
from pathlib import Path

from flask import Flask
from flask_cors import CORS

from synccut.api.db import init_db
from synccut.api.job_manager import start_executor
from synccut.api.routes import bp as api_bp
from synccut.paths import (
    cleanup_old_temp_files,
    get_base_dir,
    get_sessions_dir,
)


DEFAULT_CORS_ORIGINS = [
    "https://snycut-site-ten.vercel.app",
    "http://localhost:3000",
]


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
    app.config["APP_ROOT"] = str(get_base_dir())
    app.config["UPLOAD_ROOT"] = str(get_sessions_dir())
    if config:
        app.config.update(config)

    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": app.config.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS),
            }
        },
    )

    cleanup_old_temp_files(max_age_hours=24.0)
    app.register_blueprint(api_bp)

    # Eager init for local/desktop and single-worker gunicorn.
    # Celery workers will replace job_manager.start_executor() later.
    if not app.config.get("TESTING"):
        init_db()
        if os.environ.get("SYNCCUT_SKIP_EXECUTOR", "").lower() not in ("1", "true", "yes"):
            start_executor()

    return app
