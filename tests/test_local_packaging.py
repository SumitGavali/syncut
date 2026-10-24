"""
Unit tests for paths.py and local-first packaging requirements (WP1).
"""
import os
import shutil
import tempfile
import time
from pathlib import Path
import pytest

from synccut.paths import (
    get_base_dir,
    get_user_data_dir,
    get_sessions_dir,
    get_audio_cache_dir,
    get_ffmpeg_path,
    get_ffprobe_path,
    cleanup_old_temp_files,
)
from synccut.api.factory import find_free_port


def test_user_data_dir_resolution():
    data_dir = get_user_data_dir()
    assert data_dir.exists()
    assert "SyncCut" in str(data_dir)


def test_subdirectories_creation():
    sessions = get_sessions_dir()
    audio = get_audio_cache_dir()
    assert sessions.exists()
    assert audio.exists()


def test_ffmpeg_and_ffprobe_resolution():
    ffmpeg = get_ffmpeg_path()
    ffprobe = get_ffprobe_path()
    assert ffmpeg is not None and len(ffmpeg) > 0
    assert ffprobe is not None and len(ffprobe) > 0
    # On this machine, it should resolve to an existing executable
    assert os.path.isfile(ffmpeg) or ffmpeg == "ffmpeg"
    assert os.path.isfile(ffprobe) or ffprobe == "ffprobe"


def test_find_free_port():
    port = find_free_port(5000)
    assert isinstance(port, int)
    assert 1024 <= port <= 65535


def test_cleanup_old_temp_files():
    cache_dir = get_audio_cache_dir()
    dummy_file = cache_dir / "old_test_audio.wav"
    dummy_file.write_text("dummy")

    # Set file modification time to 48 hours ago
    past_time = time.time() - (48 * 3600)
    os.utime(dummy_file, (past_time, past_time))

    cleanup_old_temp_files(max_age_hours=24.0)
    assert not dummy_file.exists()
