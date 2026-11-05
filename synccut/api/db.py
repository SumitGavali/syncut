import sqlite3
import os
import hashlib
import secrets
from pathlib import Path
from datetime import datetime

from synccut.paths import get_user_data_dir

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
    """Create tables if they do not exist and ensure columns."""
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                token TEXT,
                plan TEXT DEFAULT 'Pro Plan',
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL,
                camera_count INTEGER DEFAULT 2,
                duration TEXT DEFAULT '00:00:00',
                thumbnail_url TEXT,
                confidence_score REAL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
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


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    ).hex()
    return salt, hashed


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, calculated = hash_password(password, salt)
    return secrets.compare_digest(calculated, expected_hash)


def create_user(email: str, name: str, password: str) -> dict:
    email_clean = email.strip().lower()
    name_clean = name.strip() if name and name.strip() else email_clean.split("@")[0]
    salt, p_hash = hash_password(password)
    user_id = f"usr_{secrets.token_hex(8)}"
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow().isoformat()

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users (id, email, name, password_hash, salt, token, plan, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, email_clean, name_clean, p_hash, salt, token, "Pro Plan", now),
        )
        conn.commit()
        return {
            "id": user_id,
            "email": email_clean,
            "name": name_clean,
            "token": token,
            "plan": "Pro Plan",
        }
    finally:
        conn.close()


def authenticate_user(email_or_username: str, password: str) -> dict | None:
    identifier = email_or_username.strip().lower()
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE LOWER(email) = ? OR LOWER(name) = ?",
            (identifier, identifier),
        )
        row = cur.fetchone()
        if not row:
            return None

        salt = row["salt"]
        stored_hash = row["password_hash"]
        if not verify_password(password, salt, stored_hash):
            return None

        # Issue fresh token
        token = secrets.token_urlsafe(32)
        cur.execute("UPDATE users SET token = ? WHERE id = ?", (token, row["id"]))
        conn.commit()
        return {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "token": token,
            "plan": row["plan"] if "plan" in row.keys() else "Pro Plan",
        }
    finally:
        conn.close()


def get_user_by_token(token: str) -> dict | None:
    if not token:
        return None
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE token = ?", (token,))
        row = cur.fetchone()
        if row:
            return {
                "id": row["id"],
                "email": row["email"],
                "name": row["name"],
                "plan": row["plan"] if "plan" in row.keys() else "Pro Plan",
            }
        return None
    finally:
        conn.close()


def revoke_user_token(token: str) -> None:
    if not token:
        return
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET token = NULL WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def get_user_projects(user_id: str) -> list[dict]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM projects WHERE user_id = ? ORDER BY rowid DESC",
            (user_id,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"] or "",
                "status": r["status"],
                "cameraCount": r["camera_count"],
                "duration": r["duration"] or "00:00:00",
                "updatedAt": r["updated_at"],
                "thumbnailUrl": r["thumbnail_url"] or "https://images.unsplash.com/photo-1574717024653-61fd2cf4d44d?auto=format&fit=crop&w=640&q=80",
                "confidenceScore": float(r["confidence_score"] or 1.0),
            }
            for r in rows
        ]
    finally:
        conn.close()


def create_user_project(user_id: str, project_data: dict) -> dict:
    pid = project_data.get("id") or f"proj-{secrets.token_hex(6)}"
    name = project_data.get("name") or "New Project"
    desc = project_data.get("description", "Multicam editing session")
    status = project_data.get("status", "Draft")
    camera_count = int(project_data.get("cameraCount", 2))
    duration = project_data.get("duration", "00:00:00")
    thumb = project_data.get("thumbnailUrl", "https://images.unsplash.com/photo-1574717024653-61fd2cf4d44d?auto=format&fit=crop&w=640&q=80")
    conf = float(project_data.get("confidenceScore", 1.0))
    now = datetime.utcnow().strftime("%b %d, %Y")

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO projects (
                id, user_id, name, description, status, camera_count,
                duration, thumbnail_url, confidence_score, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, user_id, name, desc, status, camera_count, duration, thumb, conf, now, now),
        )
        conn.commit()
        return {
            "id": pid,
            "name": name,
            "description": desc,
            "status": status,
            "cameraCount": camera_count,
            "duration": duration,
            "thumbnailUrl": thumb,
            "confidenceScore": conf,
            "updatedAt": now,
        }
    finally:
        conn.close()


def delete_user_project(user_id: str, project_id: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_user_project(user_id: str, project_id: str, updates: dict) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id))
        row = cur.fetchone()
        if not row:
            return False

        status = updates.get("status", row["status"])
        name = updates.get("name", row["name"])
        now = datetime.utcnow().strftime("%b %d, %Y")
        cur.execute(
            "UPDATE projects SET status = ?, name = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (status, name, now, project_id, user_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()
