"""
extract.py — pulls mono 16kHz audio out of any video/audio source using FFmpeg.
This is the common format every downstream sync step assumes.
"""
import subprocess
import os

from synccut.paths import get_ffmpeg_path, get_ffprobe_path

TARGET_SR = 16000  # 16kHz mono is plenty for timing correlation (Module 5 reasoning)

def extract_audio(input_path, output_dir="_audio_cache"):
    """
    Extract mono 16kHz WAV from any video or audio file with fast caching.
    Returns path to the extracted wav.
    """
    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(input_path))[0]
    out_path = os.path.join(output_dir, f"{base}.wav")

    # Fast cache check: if out_path exists and has non-zero size, reuse it
    if os.path.exists(out_path) and os.path.getsize(out_path) > 44:
        try:
            if os.path.getmtime(out_path) >= os.path.getmtime(input_path):
                return out_path
        except OSError:
            pass

    cmd = [
        get_ffmpeg_path(), "-y", "-i", input_path,
        "-vn",                # no video
        "-ac", "1",           # mono
        "-ar", str(TARGET_SR),# 16kHz
        "-loglevel", "error",
        out_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed on {input_path}:\n{result.stderr}")
    return out_path


def extract_audio_batch(input_paths, output_dir="_audio_cache", max_workers=None):
    """
    Extract audio for multiple files concurrently across CPU cores.
    Significantly speeds up multi-camera ingest for wedding/event footage.
    """
    from concurrent.futures import ThreadPoolExecutor
    if max_workers is None:
        # On memory-constrained cloud environments (e.g. Render free 512MB RAM),
        # limit concurrent ffmpeg decoders to avoid OOM killer.
        detected_cpus = os.cpu_count() or 1
        max_workers = min(len(input_paths), min(detected_cpus, 2))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(lambda p: extract_audio(p, output_dir=output_dir), input_paths))


def get_duration(input_path):
    """Returns duration in seconds using ffprobe."""
    cmd = [
        get_ffprobe_path(), "-v", "quiet", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", input_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {input_path}:\n{result.stderr}")
    return float(result.stdout.strip())
