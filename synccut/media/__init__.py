"""Media I/O: FFmpeg extraction, proxies, binary resolution helpers."""

from synccut.media.extract import (
    extract_audio,
    extract_audio_batch,
    get_duration,
)

__all__ = [
    "extract_audio",
    "extract_audio_batch",
    "get_duration",
]
