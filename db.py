import sqlite3
import os
from pathlib import Path

from paths import get_user_data_dir

_DB_PATH = None

def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        data_dir = get_user_data_dir()
        _DB_PATH = data_dir / "synccut.db"
    return _DB_PATH

def get_connection():
    """Return a SQLite connection. Caller must close it."""
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables if they do not exist."""
    db_path = _get_db_path()
    os.makedirs(db_path.parent, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

def record_session(session_id: str, status: str = "created"):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO sessions (session_id, created_at, status) VALUES (?, datetime('now'), ?)",
            (session_id, status),
        )
        conn.commit()
    finally:
        conn.close()
