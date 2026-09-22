"""
drift.py — Multi-window drift detection, robust linear regression, and signal/timeline correction.
Phase 3: Fits offset(t) = a + b*t, calculates confidence intervals, corrects drift via resampling or piecewise timeline adjustment,
and produces before/after drift reports.
"""
import numpy as np
from scipy import signal
from scipy.stats import t as student_t

from config import DEFAULT_DRIFT_WINDOW_SEC, DRIFT_CORRECT_THRESHOLD_MS_PER_HR


def windowed_offsets(sig1, sig2, fs, window_sec=DEFAULT_DRIFT_WINDOW_SEC, hop_sec=None, max_tau=10.0, use_phat=True):
    """
    Compute offset and confidence across sliding time windows.
    Returns list of dicts: [{"window_start_sec", "offset_sec", "confidence", "features"}]
    """
    from sync_engine import gcc_phat

    if hop_sec is None:
        hop_sec = window_sec / 2.0

    win_samples = int(window_sec * fs)
    hop_samples = int(hop_sec * fs)

    results = []
    min_len = min(len(sig1), len(sig2))
    pos = 0

    while pos + win_samples <= min_len:
        chunk1 = sig1[pos : pos + win_samples]
        chunk2 = sig2[pos : pos + win_samples]

        offset, conf, _, feats = gcc_phat(chunk1, chunk2, fs, max_tau=max_tau, use_phat=use_phat)
        results.append({
            "window_start_sec": pos / float(fs),
            "offset_sec": offset,
            "confidence": conf,
            "features": feats,
        })
        pos += hop_samples

    return results


def analyze_drift(windowed_results, min_confidence=0.3, alpha=0.05):
    """
    Fit robust linear regression: offset(t) = a + b * t
    Computes slope b in ms/hr and 95% confidence interval for b.
    """
    reliable = [r for r in windowed_results if r["confidence"] >= min_confidence]
    if len(reliable) < 3:
        return {
            "drift_ms_per_hour": 0.0,
            "drift_ci_lower_ms_per_hour": 0.0,
            "drift_ci_upper_ms_per_hour": 0.0,
            "intercept_sec": 0.0,
            "slope_sec_per_sec": 0.0,
            "reliable_windows": len(reliable),
            "total_windows": len(windowed_results),
            "is_significant": False,
            "note": "Insufficient high-confidence windows to estimate drift.",
        }

    times = np.array([r["window_start_sec"] for r in reliable], dtype=float)
    offsets = np.array([r["offset_sec"] for r in reliable], dtype=float)

    n = len(times)
    # Robust fit using least squares / polyfit
    slope, intercept = np.polyfit(times, offsets, 1)

    # Compute Residuals and Standard Errors for Confidence Interval
    y_pred = slope * times + intercept
    residuals = offsets - y_pred
    dof = max(1, n - 2)
    residual_variance = np.sum(residuals ** 2) / float(dof)

    times_mean = np.mean(times)
    sxx = np.sum((times - times_mean) ** 2)
    slope_se = np.sqrt(residual_variance / (sxx + 1e-10))

    # Student-t multiplier for (1 - alpha) confidence interval
    t_val = float(student_t.ppf(1.0 - alpha / 2.0, df=dof)) if dof > 0 else 1.96

    slope_ci_lower = slope - t_val * slope_se
    slope_ci_upper = slope + t_val * slope_se

    # Convert to ms/hour: 1 sec/sec = 1,000,000 ms / 1 hour (3600 sec)
    ms_per_hr_factor = 3600.0 * 1000.0
    drift_ms_hr = slope * ms_per_hr_factor
    drift_ci_lower = slope_ci_lower * ms_per_hr_factor
    drift_ci_upper = slope_ci_upper * ms_per_hr_factor

    is_significant = bool(abs(drift_ms_hr) >= DRIFT_CORRECT_THRESHOLD_MS_PER_HR)

    return {
        "drift_ms_per_hour": round(float(drift_ms_hr), 2),
        "drift_ci_lower_ms_per_hour": round(float(drift_ci_lower), 2),
        "drift_ci_upper_ms_per_hour": round(float(drift_ci_upper), 2),
        "intercept_sec": float(intercept),
        "slope_sec_per_sec": float(slope),
        "reliable_windows": len(reliable),
        "total_windows": len(windowed_results),
        "is_significant": is_significant,
        "note": None,
    }


def correct_audio_drift_resample(sig, fs, slope_sec_per_sec):
    """
    Correct drift by resampling audio signal.
    If offset(t) = a + b*t, the effective clock speed is (1 + b).
    We resample by ratio speed_ratio = 1.0 + slope_sec_per_sec.
    """
    if abs(slope_sec_per_sec) < 1e-8:
        return sig

    speed_ratio = 1.0 + slope_sec_per_sec
    new_length = int(round(len(sig) / speed_ratio))
    resampled_sig = signal.resample(sig, new_length)
    return resampled_sig


def generate_piecewise_drift_offsets(duration_sec, initial_offset, drift_ms_per_hr, segment_len_sec=10.0):
    """
    Generate piecewise linear timeline segment offsets for FCPXML / OTIO export
    when resampling is not performed.
    """
    slope = (drift_ms_per_hr / 1000.0) / 3600.0
    num_segments = max(1, int(np.ceil(duration_sec / segment_len_sec)))

    segments = []
    for i in range(num_segments):
        t_start = i * segment_len_sec
        t_end = min(duration_sec, (i + 1) * segment_len_sec)
        t_mid = (t_start + t_end) / 2.0
        offset_at_mid = initial_offset + slope * t_mid
        segments.append({
            "segment_index": i,
            "start_sec": t_start,
            "end_sec": t_end,
            "offset_sec": offset_at_mid,
        })
    return segments


def create_drift_report(before_info, after_info):
    """
    Generate before and after drift comparison report dict.
    """
    return {
        "before_drift_ms_per_hr": before_info.get("drift_ms_per_hour"),
        "after_drift_ms_per_hr": after_info.get("drift_ms_per_hour"),
        "corrected": after_info.get("is_significant", False) or before_info.get("is_significant", False),
        "status": "Drift Corrected" if before_info.get("is_significant") else "Drift within limits",
    }
