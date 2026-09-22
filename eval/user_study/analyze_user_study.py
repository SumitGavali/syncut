"""
analyze_user_study.py — Statistical analysis script for SyncCut user study data.
Computes time saved %, mean error reduction, and generates summary metrics.
"""
import csv
import os
import numpy as np


def analyze_study():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    timing_path = os.path.join(script_dir, "timing_sheet.csv")
    error_path = os.path.join(script_dir, "error_count_sheet.csv")

    if not os.path.exists(timing_path) or not os.path.exists(error_path):
        print("Data sheets not found.")
        return

    times_manual = []
    times_synccut = []

    with open(timing_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            times_manual.append(float(row["Time_Manual_Sec"]))
            times_synccut.append(float(row["Time_SyncCut_Sec"]))

    errors_manual = []
    errors_synccut = []

    with open(error_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            errors_manual.append(float(row["Manual_Sync_Errors_Frames"]))
            errors_synccut.append(float(row["SyncCut_Sync_Errors_Frames"]))

    avg_manual_time = np.mean(times_manual)
    avg_synccut_time = np.mean(times_synccut)
    time_saved_pct = ((avg_manual_time - avg_synccut_time) / avg_manual_time) * 100.0

    avg_manual_err = np.mean(errors_manual)
    avg_synccut_err = np.mean(errors_synccut)

    print("=" * 70)
    print("USER STUDY STATISTICAL SUMMARY")
    print("=" * 70)
    print(f"Average Manual Sync Time:    {avg_manual_time:.1f} sec ({avg_manual_time/60.0:.1f} min)")
    print(f"Average SyncCut Sync Time:   {avg_synccut_time:.1f} sec ({avg_synccut_time/60.0:.1f} min)")
    print(f"Time Saved:                  {time_saved_pct:.1f}%")
    print("-" * 70)
    print(f"Average Manual Sync Error:   {avg_manual_err:.2f} frames")
    print(f"Average SyncCut Sync Error:  {avg_synccut_err:.2f} frames")
    print("=" * 70)


if __name__ == "__main__":
    analyze_study()
