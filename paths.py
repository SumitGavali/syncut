"""
paths.py — Centralized path and environment resolver for SyncCut.
Handles:
- Per-user data directory (UserData / AppData / LocalShare)
- Bundled FFmpeg & FFprobe binary resolution (PyInstaller frozen or development)
- Temp audio and session cache cleanup
"""
import os
import sys
import shutil
import time
from pathlib import Path
from platformdirs import user_data_dir

APP_NAME = "SyncCut"
APP_AUTHOR = "SyncCut"


def get_base_dir() -> Path:
    """Return the application base directory (frozen bundle or dev root)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def get_user_data_dir() -> Path:
    """Return the per-user data directory for sessions, cache, and results."""
    data_dir = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_sessions_dir() -> Path:
    """Return user data directory for session files and uploads."""
    d = get_user_data_dir() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_audio_cache_dir() -> Path:
    """Return user data directory for extracted audio wavs."""
    d = get_user_data_dir() / "audio_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_results_dir() -> Path:
    """Return user data directory for exported timelines and reports."""
    d = get_user_data_dir() / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_binary(binary_name: str) -> str:
    """
    Resolve path to binary (e.g. ffmpeg, ffprobe).
    Priority:
    1. Bundled inside PyInstaller _MEIPASS / app folder (e.g., bin/ or ffmpeg_bin/)
    2. Side-by-side with sys.executable
    3. System PATH
    """
    ext = ".exe" if sys.platform.startswith("win") else ""
    target = f"{binary_name}{ext}"

    # 1. Bundled in frozen app _MEIPASS or dev root
    base = get_base_dir()
    candidates = [
        base / target,
        base / "bin" / target,
        base / "ffmpeg_bin" / target,
        Path(sys.executable).parent / target,
        Path(sys.executable).parent / "bin" / target,
    ]

    for candidate in candidates:
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)

    # 2. System PATH
    system_path = shutil.which(binary_name)
    if system_path:
        return system_path

    # Fallback to plain binary name so standard error message is raised if missing
    return binary_name


def get_ffmpeg_path() -> str:
    return resolve_binary("ffmpeg")


def get_ffprobe_path() -> str:
    return resolve_binary("ffprobe")


def cleanup_old_temp_files(max_age_hours: float = 24.0):
    """
    Automatically clean up temporary audio files and abandoned session folders
    older than max_age_hours.
    """
    cutoff = time.time() - (max_age_hours * 3600)
    for folder in [get_audio_cache_dir(), get_sessions_dir()]:
        if not folder.exists():
            continue
        for item in folder.iterdir():
            try:
                mtime = item.stat().st_mtime
                if mtime < cutoff:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
            except Exception:
                pass
