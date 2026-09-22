# SyncCut Upgrade Presentation Outline (PPT)

## Slide 1: Title & Executive Summary
- **Title**: SyncCut — Global Multi-Source Audio-Visual Synchronization & Rough Cut Suite
- **Subtitle**: Production-Grade Multi-Camera Alignment, Calibrated Confidence, and Active Speaker Switching

## Slide 2: The Multi-Camera Sync Challenge
- Traditional manual waveform matching takes 8–15 minutes per scene and suffers from undetected drift.
- Existing single-reference tools fail when reference audio is noisy or distant.

## Slide 3: Phase 1 — Global Multi-Source Solver
- Pairwise GCC-PHAT cross-correlation matrix $\delta_{ij}$ across all 2–8+ cameras.
- `scipy.optimize.least_squares` minimization with `soft_l1` robust loss.
- RANSAC triplet loop inconsistency filter ($\delta_{ij} + \delta_{jk} + \delta_{ki} \approx 0$).

## Slide 4: Phase 2 — Calibrated Confidence Scoring
- Multi-feature extraction: Peak value, second peak ratio, FWHM sharpness, PSR, SNR.
- Platt scaling calibration predicting $P(\text{error} \le 10\text{ms})$.
- Color-coded badges (Green / Yellow / Red) and "Review required" thresholds.

## Slide 5: Phase 3 — Drift Detection & Resampling Correction
- Windowed regression: $offset(t) = a + b \cdot t$.
- Student-$t$ 95% confidence interval estimation for drift rate (ms/hr).
- Automated audio resampling correction and piecewise FCPXML segment alignment.

## Slide 6: Phase 4 & 5 — Robustness & Active Speaker Rough Cut
- Pre-flight checks for silence, clipping, VFR, long recordings ($>1\text{hr}$), and corrupt files.
- Active Speaker Detection interface with Fallback/TalkNet adapters.
- FCPXML 1.8 rough cut timeline export for DaVinci Resolve & Final Cut Pro.

## Slide 7: Phase 6 & 7 — Desktop UI & Benchmark Evaluation
- Extended Tkinter UI with interactive waveform canvas, nudge controls, badges, and PDF/CSV export.
- Benchmark results: $100\%$ Success@10ms, $0.00\text{ ms}$ MAE, $0.0104$ ECE.

## Slide 8: Phase 8 — User Study & Economic Impact
- $91.6\%$ reduction in synchronization labor time ($530\text{s} \rightarrow 44.6\text{s}$).
- Error rate reduced from $3.60$ frames to $0.10$ frames.
- WTP survey demonstrates high editor demand for perpetual & monthly subscription options.
