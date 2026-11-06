"""Video-duration and account-tier quota enforcement."""
from __future__ import annotations

import subprocess
from os import PathLike
from pathlib import Path
from typing import Iterable

from synccut.api.db import get_user_tier
from synccut.paths import get_ffprobe_path

TIER_LIMITS = {
    "free": {
        "max_cameras": 2,
        "max_duration_seconds": 10 * 60,
        "max_export_height": 720,
        "full_ai_cuts": False,
    },
    "pro": {
        "max_cameras": 8,
        "max_duration_seconds": 60 * 60,
        "max_export_height": 2160,
        "full_ai_cuts": True,
    },
    "studio": {
        "max_cameras": 8,
        "max_duration_seconds": 60 * 60,
        "max_export_height": 2160,
        "full_ai_cuts": True,
    },
}


def check_video_duration(file_path: str | PathLike[str]) -> float:
    """Return a media file's duration in seconds using ffprobe."""
    command = [
        get_ffprobe_path(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        duration = float(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise ValueError(f"Could not read media duration for {file_path}: {error}") from error
    if duration < 0:
        raise ValueError(f"ffprobe returned an invalid duration for {file_path}.")
    return duration


def enforce_limits(user_id: str, files: Iterable[str | PathLike[str]]) -> None:
    """Reject uploads exceeding the account's camera-count or clip-duration limit."""
    file_paths = [Path(file_path) for file_path in files]
    tier = get_user_tier(user_id)
    limits = TIER_LIMITS[tier]
    if len(file_paths) > limits["max_cameras"]:
        raise PermissionError(
            f"The {tier.title()} tier allows up to {limits['max_cameras']} cameras."
        )

    max_duration = limits["max_duration_seconds"]
    for file_path in file_paths:
        duration = check_video_duration(file_path)
        if duration > max_duration:
            minutes = max_duration // 60
            raise PermissionError(
                f"The {tier.title()} tier allows clips up to {minutes} minutes."
            )
