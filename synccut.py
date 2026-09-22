"""
synccut.py — CLI entry point for SyncCut.
Phase 1-6 CLI: Supports global multi-source solver, calibrated confidence scoring,
drift detection/correction, failure case checks, and report generation.

Usage:
    python synccut.py --reference ref.wav --inputs c1.mp4 c2.mp4 --sync-mode global --drift-correct
"""
import argparse
import json
import os
import sys

from confidence import badge_and_status_from_confidence, extract_correlation_features
from config import DEFAULT_SYNC_MODE, DEFAULT_DRIFT_WINDOW_SEC, DRIFT_CORRECT_THRESHOLD_MS_PER_HR
from drift import windowed_offsets, analyze_drift, correct_audio_drift_resample
from extract import extract_audio
from robustness import preflight_media_check, check_sample_rates
from sync_engine import load_wav, solve_multi_source_sync


def process_all_sources(reference_path, input_paths, sync_mode="global", drift_correct=False, drift_window_sec=DEFAULT_DRIFT_WINDOW_SEC, drift_threshold_ms_hr=DRIFT_CORRECT_THRESHOLD_MS_PER_HR):
    """
    Process reference + N input sources together using the requested sync_mode.
    """
    print(f"  Extracting audio for reference: {os.path.basename(reference_path)}")
    ref_wav = extract_audio(reference_path)
    sr_ref, ref_sig = load_wav(ref_wav)

    valid, ref_flags = preflight_media_check(reference_path, ref_sig, sr_ref)
    if not valid:
        print(f"  WARNING: Reference audio quality warning: {ref_flags}")

    all_signals = [ref_sig]
    all_paths = [reference_path] + input_paths
    labels = ["Reference"] + [f"Camera {chr(65+i)}" if i < 26 else f"Source {i+1}" for i in range(len(input_paths))]

    for idx, src_path in enumerate(input_paths):
        print(f"  Extracting audio for source {idx+1}: {os.path.basename(src_path)}")
        src_wav = extract_audio(src_path)
        sr_src, src_sig = load_wav(src_wav)
        sr_ok, msg = check_sample_rates(sr_ref, sr_src)
        if not sr_ok:
            print(f"  WARNING: {msg}")
        all_signals.append(src_sig)

    print(f"  Running multi-source alignment in '{sync_mode}' mode...")
    offsets, confidences, feature_dicts = solve_multi_source_sync(
        all_signals, sr_ref, sync_mode=sync_mode, ref_index=0
    )

    results = []
    for idx in range(len(all_paths)):
        label = labels[idx]
        src_path = all_paths[idx]
        fname = os.path.basename(src_path)
        offset = float(offsets[idx])
        conf = float(confidences[idx])

        if idx == 0:
            drift_info = {"drift_ms_per_hour": 0.0, "is_significant": False, "reliable_windows": "-", "total_windows": "-"}
            badge, status = "green", "Good (reference)"
        else:
            print(f"  Analyzing drift across windows for {label}...")
            windows = windowed_offsets(ref_sig, all_signals[idx], sr_ref, window_sec=drift_window_sec)
            drift_info = analyze_drift(windows)
            badge, status = badge_and_status_from_confidence(conf, drift_info["drift_ms_per_hour"])

            if drift_correct and drift_info.get("is_significant", False):
                print(f"  Correcting drift for {label} (Drift: {drift_info['drift_ms_per_hour']} ms/hr)...")
                slope = drift_info["slope_sec_per_sec"]
                corrected_sig = correct_audio_drift_resample(all_signals[idx], sr_ref, slope)
                all_signals[idx] = corrected_sig
                status += " [Drift Resampled]"

        results.append({
            "source": label,
            "file": fname,
            "offset_sec": round(offset, 3),
            "confidence": round(conf, 3),
            "drift_ms_per_hour": drift_info["drift_ms_per_hour"],
            "reliable_windows": f"{drift_info.get('reliable_windows', '-')}/{drift_info.get('total_windows', '-')}",
            "badge": badge,
            "status": status,
        })

    return results


def main():
    parser = argparse.ArgumentParser(description="SyncCut — Global Multi-Camera Synchronization Suite")
    parser.add_argument("--reference", required=True, help="Reference audio/video file")
    parser.add_argument("--inputs", required=True, nargs="+", help="Input video/audio source files to sync")
    parser.add_argument("--sync-mode", choices=["global", "reference"], default=DEFAULT_SYNC_MODE, help="Sync solver mode: global (least squares matrix) or reference (single-pair)")
    parser.add_argument("--drift-correct", action="store_true", help="Enable automatic drift resampling/piecewise correction")
    parser.add_argument("--drift-window", type=float, default=DEFAULT_DRIFT_WINDOW_SEC, help="Window size for drift analysis in seconds")
    parser.add_argument("--drift-threshold", type=float, default=DRIFT_CORRECT_THRESHOLD_MS_PER_HR, help="Drift threshold in ms/hr to trigger correction")
    parser.add_argument("--output", default="sync_report.json", help="Output report path (JSON)")

    args = parser.parse_args()

    print(f"SyncCut running -- reference: {args.reference}, mode: {args.sync_mode}")
    results = process_all_sources(
        args.reference,
        args.inputs,
        sync_mode=args.sync_mode,
        drift_correct=args.drift_correct,
        drift_window_sec=args.drift_window,
        drift_threshold_ms_hr=args.drift_threshold,
    )

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 80)
    print("SYNC REPORT")
    print("=" * 80)
    print(f"{'Source':<12}{'Offset':>10}{'Drift/hr':>12}{'Confidence':>12}{'Badge':>10}{'Status':>22}")
    print("-" * 80)
    for r in results:
        offset_str = f"{r['offset_sec']:+.3f}s" if r['offset_sec'] is not None else "N/A"
        drift_str = f"{r['drift_ms_per_hour']}ms" if r['drift_ms_per_hour'] is not None else "N/A"
        conf_str = f"{r['confidence']*100:.0f}%"
        badge_str = r["badge"].upper()
        print(f"{r['source']:<12}{offset_str:>10}{drift_str:>12}{conf_str:>12}{badge_str:>10}{r['status']:>22}")
    print("=" * 80)
    print(f"\nFull report saved to: {args.output}")


if __name__ == "__main__":
    main()
