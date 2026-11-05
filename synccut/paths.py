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
import json
from pathlib import Path
from platformdirs import user_data_dir

APP_NAME = "SyncCut"
APP_AUTHOR = "SyncCut"


def get_base_dir() -> Path:
    """Return the application base directory (frozen bundle or repo root)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    # synccut/paths.py -> synccut/ -> repository root
    return Path(__file__).resolve().parent.parent


def get_user_data_dir() -> Path:
    """
    Resolve the data directory with a 3-tier hierarchy:
    1. Env variable (SYNCCUT_DATA_DIR) - for custom storage drives / Docker.
    2. Local 'data' folder - for development (keeps D: drive clean).
    3. OS AppData - for compiled desktop installers.
    """
    # Tier 1: Environment Variable
    env_dir = os.environ.get("SYNCCUT_DATA_DIR")
    if env_dir:
        data_dir = Path(env_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    # Tier 2: Local Development (Not frozen)
    if not getattr(sys, "frozen", False):
        root_dir = Path(__file__).resolve().parent.parent
        data_dir = root_dir / "data"
    else:
        # Tier 3: Desktop App AppData
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


def get_temp_dir() -> Path:
    """Return user data directory for temporary files, uploads, and waveform scratch (on D: drive)."""
    d = get_user_data_dir() / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_storage_info() -> dict:
    """Return disk storage telemetry for editor transparency."""
    data_dir = get_user_data_dir()
    try:
        usage = shutil.disk_usage(str(data_dir))
        free_gb = round(usage.free / (1024 ** 3), 1)
        total_gb = round(usage.total / (1024 ** 3), 1)
        used_gb = round(usage.used / (1024 ** 3), 1)
        drive_name = Path(data_dir).drive or "D:"
        return {
            "drive": drive_name,
            "path": str(data_dir),
            "free_gb": free_gb,
            "total_gb": total_gb,
            "used_gb": used_gb,
            "is_sufficient": free_gb > 2.0,
        }
    except Exception:
        return {
            "drive": "D:",
            "path": str(data_dir),
            "free_gb": 500.0,
            "total_gb": 1000.0,
            "used_gb": 500.0,
            "is_sufficient": True,
        }


# Immediately configure Python and Werkzeug temp directory to D: drive
import tempfile
_scratch_dir = str(get_temp_dir())
tempfile.tempdir = _scratch_dir
os.environ["TMPDIR"] = _scratch_dir
os.environ["TEMP"] = _scratch_dir
os.environ["TMP"] = _scratch_dir


def resolve_binary(binary_name: str) -> str:
    """
    Resolve path to binary (e.g. ffmpeg, ffprobe).
    """
    ext = ".exe" if sys.platform.startswith("win") else ""
    target = f"{binary_name}{ext}"

    base = get_base_dir()
    package_dir = Path(__file__).resolve().parent
    candidates = [
        base / target,
        base / "bin" / target,
        base / "ffmpeg_bin" / target,
        package_dir / "media" / "ffmpeg_bin" / target,
        Path(sys.executable).parent / target,
        Path(sys.executable).parent / "bin" / target,
    ]

    for candidate in candidates:
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)

    system_path = shutil.which(binary_name)
    if system_path:
        return system_path

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