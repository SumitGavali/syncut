# SyncCut Upgrade & Migration Plan

## Executive Summary
This document outlines the complete technical transformation of SyncCut from a basic single-reference sync script into a multi-camera synchronization, drift-correction, active speaker rough-cut, and evaluation system.

## Phase Overview

### Phase 1 — Global Multi-Source Synchronization
- Replaced pairwise single-reference sync with a global solver (`sync_engine.py`).
- Pairwise GCC-PHAT matrix $\delta_{ij}$ and confidence weight matrix $w_{ij}$ computed for $N$ sources ($2 \le N \le 8+$).
- Solves global start offsets $t_i$ using `scipy.optimize.least_squares` with robust loss (`soft_l1`).
- Implemented RANSAC triplet loop inconsistency filter to prune outlier cross-correlation peaks.
- Exposed `--sync-mode {global, reference}` CLI flag.

### Phase 2 — Calibrated Confidence Scoring
- Replaced raw peak ratio with 5 correlation features (`confidence.py`): primary peak, second peak ratio, FWHM sharpness, PSR, and SNR.
- Implemented Platt Scaling and Isotonic Regression calibration for probability prediction $P(\text{error} \le 10\text{ms})$.
- Metrics: Expected Calibration Error (ECE) and Area Under ROC (AUC).
- Badge assignment: Green ($\ge 0.8$), Yellow ($0.4 - 0.79$), Red ($< 0.4$), with "Review required" thresholds.

### Phase 3 — Drift Detection & Correction
- Sliding window correlation across intervals (`drift.py`).
- Fits robust linear regression $offset(t) = a + b \cdot t$ with 95% confidence intervals for drift rate $b$ (ms/hr).
- Corrects drift via signal resampling (`scipy.signal.resample`) or piecewise linear FCPXML timeline segmentation.

### Phase 4 — Robustness & Failure Handling
- Pre-flight checks (`robustness.py`) for missing audio, silent tracks, clipped audio, sample rate mismatches, VFR, long recordings ($>1\text{hr}$), non-overlapping media, and corruption.
- Suite of 7 robustness unit tests in `tests/robustness/test_failure_cases.py`.

### Phase 5 — Active Speaker / Rough Cut
- Interface for Active Speaker Detection (`rough_cut.py`) supporting TalkNet/Light-ASD models with fallback energy/spectral/diarization heuristics.
- Global timeline alignment, minimum shot duration enforcement ($\ge 1.5\text{s}$), and FCPXML 1.8 rough cut export.

### Phase 6 — Manual Correction UI & Reports
- Extended Tkinter GUI (`synccut_gui.py`) featuring visual waveform overlay canvas, confidence badges, "Review required" panel, manual nudge controls ($\pm 100\text{ms}, \pm 10\text{ms}, \pm 1\text{ frame}$), drift display (ms/hr), and direct export for CSV, PDF, and FCPXML timeline.

### Phase 7 — Evaluation Harness
- Reproducible evaluation harness (`eval/evaluate_sync.py`) calculating MAE (ms), Success@10ms/1frame, ECE, AUC, RTF, memory, and baseline/ablation comparisons.

### Phase 8 — User Study Framework
- Complete survey framework (`eval/user_study/`) with task scripts, timing sheets, error count sheets, SUS, NASA-TLX, WTP questionnaires, and statistical analysis scripts.

### Phase 9 — System Engineering
- Requirements specification, architecture diagrams, GitHub Actions CI workflow, `pyproject.toml`, PyInstaller `synccut.spec`, and test suite.
