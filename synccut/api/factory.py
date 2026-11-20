from __future__ import annotations
import os
import secrets
import socket
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, send_from_directory
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

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:5173",
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
    package_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )

    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024
    app.config["SECRET_KEY"] = _get_secret_key()
    app.config["APP_ROOT"] = str(get_base_dir())
    app.config["UPLOAD_ROOT"] = str(get_sessions_dir())
    
    # Desktop mode: relaxed cookies
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    
    if config:
        app.config.update(config)

    # Allow local desktop origins
    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": DEFAULT_CORS_ORIGINS,
                "supports_credentials": True,
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

    # Serve the compiled React frontend
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_react(path):
        # In a PyInstaller build, get_base_dir() returns the _MEIPASS folder
        dist_dir = os.path.join(get_base_dir(), 'synccut-studio', 'dist')
        if path != "" and os.path.exists(os.path.join(dist_dir, path)):
            return send_from_directory(dist_dir, path)
        else:
            return send_from_directory(dist_dir, 'index.html')

    if not app.config.get("TESTING"):
        init_db()

    return app