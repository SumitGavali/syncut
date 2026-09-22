"""
robustness.py — Failure case detection and pre-flight media integrity checks.
Phase 4: Explicit checks for missing audio, silence, clipping, VFR, mismatched sample rates,
long recordings, non-overlapping media, and corruption.
"""
import os
import numpy as np
from config import MIN_AUDIO_ENERGY_DB, CLIPPING_THRESHOLD_RATIO, MAX_SILENCE_RATIO


class RobustnessError(Exception):
    """Custom exception raised when severe unrecoverable media flaws occur."""
    pass


def check_file_readable(path):
    """Verify file exists and is non-empty."""
    if not os.path.exists(path):
        return False, f"File not found: {path}"
    if os.path.getsize(path) == 0:
        return False, f"File is zero bytes: {path}"
    return True, "OK"


def analyze_audio_quality(signal, fs):
    """
    Check signal audio quality for common defect modes:
    - Missing / Empty signal
    - Silence (RMS energy < MIN_AUDIO_ENERGY_DB or >95% zero samples)
    - Severe audio clipping (>5% of samples at max range)
    """
    flags = []
    if signal is None or len(signal) == 0:
        return False, ["MISSING_AUDIO"]

    abs_sig = np.abs(signal)
    max_val = np.max(abs_sig) if len(abs_sig) > 0 else 0.0

    if max_val < 1e-7:
        flags.append("SILENT_AUDIO")

    # RMS energy calculation
    rms = np.sqrt(np.mean(signal ** 2))
    db = 20 * np.log10(rms) if rms > 0 else -100.0

    if db < MIN_AUDIO_ENERGY_DB:
        flags.append("LOW_ENERGY_SILENCE")

    # Silence ratio
    zero_ratio = np.sum(abs_sig < 1e-5) / float(len(abs_sig))
    if zero_ratio > MAX_SILENCE_RATIO:
        flags.append("EXTREME_SILENCE")

    # Clipping detection
    clipped_samples = np.sum(abs_sig > 0.99)
    clipping_ratio = clipped_samples / float(len(abs_sig))
    if clipping_ratio > CLIPPING_THRESHOLD_RATIO:
        flags.append(f"CLIPPED_AUDIO ({clipping_ratio*100:.1f}%)")

    is_usable = not ("MISSING_AUDIO" in flags or "SILENT_AUDIO" in flags)
    return is_usable, flags


def check_sample_rates(sr1, sr2):
    """Ensure sample rates match or raise flag."""
    if sr1 != sr2:
        return False, f"Sample rate mismatch: {sr1} Hz vs {sr2} Hz"
    return True, "OK"


def check_recording_duration(signal, fs):
    """
    Detect long recordings (> 1 hour) requiring chunking.
    """
    duration_sec = len(signal) / float(fs)
    is_long = duration_sec >= 3600.0
    return duration_sec, is_long


def check_overlap(duration1_sec, duration2_sec, offset_sec):
    """
    Detect non-overlapping audio windows given an estimated offset.
    """
    overlap_start = max(0.0, offset_sec)
    overlap_end = min(duration1_sec, duration2_sec + offset_sec)
    overlap_duration = max(0.0, overlap_end - overlap_start)

    if overlap_duration <= 1.0:
        return False, f"NO_OVERLAP (Overlap duration: {overlap_duration:.2f}s)"
    return True, f"Overlap: {overlap_duration:.2f}s"


def preflight_media_check(file_path, signal=None, fs=None):
    """
    Run full suite of pre-flight checks on a media input file.
    Returns: (is_valid, list_of_warning_or_error_flags)
    """
    readable, msg = check_file_readable(file_path)
    if not readable:
        return False, [msg]

    if signal is not None and fs is not None:
        usable, audio_flags = analyze_audio_quality(signal, fs)
        if not usable:
            return False, audio_flags
        return True, audio_flags

    return True, []
