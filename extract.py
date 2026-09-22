"""
extract.py — pulls mono 16kHz audio out of any video/audio source using FFmpeg.
This is the common format every downstream sync step assumes.
"""
import subprocess
import os

TARGET_SR = 16000  # 16kHz mono is plenty for timing correlation (Module 5 reasoning)

def extract_audio(input_path, output_dir="_audio_cache"):
    """
    Extract mono 16kHz WAV from any video or audio file.
    Returns path to the extracted wav.
    """
    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(input_path))[0]
    out_path = os.path.join(output_dir, f"{base}.wav")

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
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


def get_duration(input_path):
    """Returns duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", input_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {input_path}:\n{result.stderr}")
    return float(result.stdout.strip())
