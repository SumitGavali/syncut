"""
camera_switch.py — Analyzes synchronized audio tracks and suggests which
camera should be active at each moment, based on audio energy.

Key correctness requirement: energy MUST be compared across sources at the
same real-world moment, not the same local file-index. Each source has its
own offset (from the sync report) — this module aligns every source's audio
to a shared timeline before comparing energy, using exactly the same
trim-in logic as timeline_builder.py's sync alignment.
"""
import json
import os
import numpy as np
from extract import extract_audio
from sync_engine import load_wav


def _compute_trim_in(offset_sec, max_offset):
    """Same alignment logic as timeline_builder.build_timeline: the source
    that started latest (max_offset) defines the common sync point."""
    return max(0.0, max_offset - offset_sec)


def analyze_audio_energy(audio_path, trim_in_sec=0.0, window_sec=0.5):
    """
    Analyze audio energy over time, starting from trim_in_sec so that
    window index i corresponds to the same real-world moment across all
    sources sharing the same trim alignment.
    Returns: (timestamps_global, energies_db)
    """
    wav_path = extract_audio(audio_path)
    sr, signal = load_wav(wav_path)

    if signal.ndim > 1:
        signal = np.mean(signal, axis=1)

    trim_samples = int(trim_in_sec * sr)
    signal = signal[trim_samples:]

    window_samples = int(sr * window_sec)
    if window_samples <= 0:
        return [], []

    num_windows = len(signal) // window_samples

    timestamps, energies = [], []
    for i in range(num_windows):
        start = i * window_samples
        window = signal[start:start + window_samples]
        rms = np.sqrt(np.mean(window ** 2))
        db = 20 * np.log10(rms) if rms > 0 else -100.0
        energies.append(db)
        timestamps.append(round(i * window_sec, 3))  # global timeline position

    return timestamps, energies


def generate_camera_switches(report_path, media_dir, window_sec=0.5,
                              min_energy_db=-40, min_shot_sec=1.5):
    """
    Generate camera switch SEGMENTS (not per-window flicker) based on
    offset-aligned audio energy comparison.

    Returns: list of segments [{start_sec, end_sec, camera, file, avg_energy_db}]
    """
    with open(report_path) as f:
        results = json.load(f)

    # Include every source with usable confidence — reference included,
    # since the reference camera is a valid switch candidate too.
    candidates = [r for r in results if r.get("confidence", 0) > 0.15 and r.get("offset_sec") is not None]
    if not candidates:
        return []

    max_offset = max(r["offset_sec"] for r in candidates)

    all_energies = {}
    for r in candidates:
        file_path = os.path.join(media_dir, r["file"])
        if not os.path.exists(file_path):
            print(f"  WARNING: {file_path} not found, skipping {r['source']} in switch analysis")
            continue
        trim_in = _compute_trim_in(r["offset_sec"], max_offset)
        timestamps, energies = analyze_audio_energy(file_path, trim_in_sec=trim_in, window_sec=window_sec)
        all_energies[r["source"]] = {"timestamps": timestamps, "energies": energies, "file": r["file"]}

    if not all_energies:
        return []

    # Compare across sources at each shared global window index
    num_windows = min(len(v["energies"]) for v in all_energies.values())

    per_window_winner = []
    for i in range(num_windows):
        best_camera, best_energy = None, -100.0
        for camera, data in all_energies.items():
            energy = data["energies"][i]
            if energy > min_energy_db and energy > best_energy:
                best_energy = energy
                best_camera = camera
        if best_camera is None:
            # nothing above threshold this window — hold previous camera
            # rather than leaving a gap (avoids silence-triggered flicker)
            best_camera = per_window_winner[-1]["camera"] if per_window_winner else list(all_energies.keys())[0]
            best_energy = all_energies[best_camera]["energies"][i]
        per_window_winner.append({
            "time_sec": all_energies[best_camera]["timestamps"][i],
            "camera": best_camera,
            "energy_db": round(best_energy, 1),
            "file": all_energies[best_camera]["file"]
        })

    # Merge consecutive same-camera windows into real segments
    segments = []
    for w in per_window_winner:
        if segments and segments[-1]["camera"] == w["camera"]:
            segments[-1]["end_sec"] = round(w["time_sec"] + window_sec, 3)
            segments[-1]["_energies"].append(w["energy_db"])
        else:
            segments.append({
                "start_sec": w["time_sec"],
                "end_sec": round(w["time_sec"] + window_sec, 3),
                "camera": w["camera"],
                "file": w["file"],
                "_energies": [w["energy_db"]]
            })

    # Absorb segments shorter than min_shot_sec into the previous segment,
    # to avoid unusable rapid-fire cuts from momentary energy spikes.
    cleaned = []
    for seg in segments:
        duration = seg["end_sec"] - seg["start_sec"]
        if cleaned and duration < min_shot_sec:
            cleaned[-1]["end_sec"] = seg["end_sec"]
            cleaned[-1]["_energies"].extend(seg["_energies"])
        else:
            cleaned.append(seg)

    for seg in cleaned:
        seg["avg_energy_db"] = round(sum(seg["_energies"]) / len(seg["_energies"]), 1)
        del seg["_energies"]

    return cleaned


def generate_switch_timeline(segments, output_path="camera_switches.json"):
    with open(output_path, "w") as f:
        json.dump(segments, f, indent=2)
    print(f"Camera switch segments saved to: {output_path}")
    return output_path


def print_switch_summary(segments):
    if not segments:
        print("No camera switches detected (audio may be too quiet, or all sources below confidence threshold).")
        return
    print("\n" + "=" * 70)
    print("CAMERA SWITCH SUGGESTIONS")
    print("=" * 70)
    print(f"{'Start':>8} {'End':>8} {'Duration':>10} {'Camera':<12}{'Avg Energy':>12}")
    print("-" * 70)
    for s in segments[:50]:
        duration = s["end_sec"] - s["start_sec"]
        print(f"{s['start_sec']:>7.1f}s {s['end_sec']:>7.1f}s {duration:>9.1f}s {s['camera']:<12}{s['avg_energy_db']:>10.1f}dB")
    if len(segments) > 50:
        print(f"... and {len(segments) - 50} more segments")
    print("=" * 70)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, help="sync_report.json")
    parser.add_argument("--media-dir", required=True, help="Media directory")
    parser.add_argument("--window", type=float, default=0.5, help="Analysis window (seconds)")
    parser.add_argument("--min-shot", type=float, default=1.5, help="Minimum shot duration (seconds)")
    parser.add_argument("--output", default="camera_switches.json", help="Output file")
    args = parser.parse_args()

    segments = generate_camera_switches(args.report, args.media_dir, window_sec=args.window, min_shot_sec=args.min_shot)
    generate_switch_timeline(segments, args.output)
    print_switch_summary(segments)
    