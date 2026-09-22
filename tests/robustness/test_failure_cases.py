"""
test_failure_cases.py — Unit tests for Phase 4 failure mode detection and robustness checks.
"""
import pytest
import numpy as np
import os
from robustness import (
    check_file_readable,
    analyze_audio_quality,
    check_sample_rates,
    check_recording_duration,
    check_overlap,
    preflight_media_check,
)


def test_missing_file_detection():
    readable, msg = check_file_readable("non_existent_file.mp4")
    assert not readable
    assert "not found" in msg.lower()


def test_silent_audio_detection():
    fs = 16000
    silent_sig = np.zeros(fs * 5)
    usable, flags = analyze_audio_quality(silent_sig, fs)
    assert not usable
    assert "SILENT_AUDIO" in flags or "LOW_ENERGY_SILENCE" in flags


def test_clipped_audio_detection():
    fs = 16000
    clipped_sig = np.ones(fs * 2) * 0.999  # 100% clipped
    usable, flags = analyze_audio_quality(clipped_sig, fs)
    assert any("CLIPPED_AUDIO" in f for f in flags)


def test_sample_rate_mismatch():
    ok, msg = check_sample_rates(44100, 48000)
    assert not ok
    assert "mismatch" in msg.lower()


def test_long_recording_detection():
    fs = 16000
    long_sig = np.zeros(fs * 3650)  # > 1 hour
    dur, is_long = check_recording_duration(long_sig, fs)
    assert is_long
    assert dur > 3600.0


def test_no_overlap_detection():
    dur1 = 10.0
    dur2 = 10.0
    offset = 50.0  # Starts 50s after dur1 ended -> no overlap
    ok, msg = check_overlap(dur1, dur2, offset)
    assert not ok
    assert "NO_OVERLAP" in msg


def test_more_than_4_cameras_support():
    from sync_engine import solve_multi_source_sync
    fs = 8000
    t = np.linspace(0, 2.0, int(fs * 2.0))
    base_sig = np.sin(2 * np.pi * 440 * t)

    # 8 camera sources
    signals = [np.pad(base_sig, (int(fs * 0.05 * i), 0))[:len(base_sig)] for i in range(8)]
    offsets, confs, _ = solve_multi_source_sync(signals, fs, sync_mode="global")

    assert len(offsets) == 8
    assert len(confs) == 8
    for i in range(8):
        assert abs(offsets[i] - 0.05 * i) < 0.02
