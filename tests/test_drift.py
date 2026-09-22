"""
test_drift.py — Unit tests for Phase 3 drift estimation and signal resampling correction.
"""
import pytest
import numpy as np
from drift import analyze_drift, correct_audio_drift_resample, generate_piecewise_drift_offsets


def test_analyze_drift_linear_synthetic():
    # offset(t) = 0.05 + (100 ms / 3600 sec) * t
    # Slope = 100 ms / hr
    slope_true = (100.0 / 1000.0) / 3600.0  # sec/sec
    intercept_true = 0.05

    windowed_results = []
    for t in np.linspace(0, 1800, 10):  # 30 min recording
        offset_t = intercept_true + slope_true * t + np.random.normal(0, 0.001)
        windowed_results.append({
            "window_start_sec": float(t),
            "offset_sec": float(offset_t),
            "confidence": 0.9,
        })

    info = analyze_drift(windowed_results)
    assert info["is_significant"] is True
    assert abs(info["drift_ms_per_hour"] - 100.0) < 15.0
    assert info["reliable_windows"] == 10


def test_correct_audio_drift_resample():
    fs = 8000
    t = np.linspace(0, 10.0, fs * 10)
    sig = np.sin(2 * np.pi * 440 * t)

    # 10000 ms/hr drift slope
    slope = (10.0) / 3600.0  # ~0.00277 sec/sec slope
    resampled = correct_audio_drift_resample(sig, fs, slope)

    assert len(resampled) != len(sig)
    assert abs(len(resampled) - len(sig)) >= 10


def test_generate_piecewise_drift_offsets():
    segments = generate_piecewise_drift_offsets(
        duration_sec=60.0,
        initial_offset=0.2,
        drift_ms_per_hr=120.0,
        segment_len_sec=10.0,
    )
    assert len(segments) == 6
    assert segments[0]["start_sec"] == 0.0
    assert segments[0]["end_sec"] == 10.0
    assert segments[0]["offset_sec"] > 0.2
