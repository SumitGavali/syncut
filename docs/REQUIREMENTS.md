# SyncCut System Requirements Specification

## 1. Functional Requirements

### 1.1 Global Multi-Source Synchronization (Phase 1)
- **FR-1.1**: The system MUST compute pairwise GCC-PHAT offset matrix $\delta_{ij}$ and pairwise confidence weight matrix $w_{ij}$ for $N$ input sources ($2 \le N \le 8+$).
- **FR-1.2**: The system MUST optimize global source start offsets $t_i$ relative to a designated reference track ($t_{ref} = 0$) by minimizing weighted robust loss $\sum_{i,j} w_{ij} \rho(t_i - t_j - \delta_{ij})$ using `scipy.optimize.least_squares`.
- **FR-1.3**: The system MUST apply RANSAC loop-consistency outlier rejection to zero out weights of pairwise measurements breaking triplet consistency $\delta_{ij} + \delta_{jk} + \delta_{ki} \approx 0$.
- **FR-1.4**: The system MUST support fallback reference-only synchronization via CLI `--sync-mode {global,reference}`.

### 1.2 Calibrated Confidence Scoring (Phase 2)
- **FR-2.1**: The system MUST extract 5 feature metrics from cross-correlation curves: primary peak amplitude, second-highest peak ratio, peak sharpness (FWHM), peak-to-sidelobe ratio (PSR), and correlation SNR.
- **FR-2.2**: The system MUST convert feature vectors into calibrated probability $P(\text{error} \le 10\text{ms})$ using Platt Scaling or Isotonic Regression.
- **FR-2.3**: The system MUST output Expected Calibration Error (ECE), Area Under ROC (AUC), and reliability diagrams in evaluation reports.
- **FR-2.4**: The system MUST assign color-coded badges (Green $\ge 0.8$, Yellow $0.4-0.79$, Red $< 0.4$) and flag "Review required" when calibrated confidence $< 0.4$.

### 1.3 Drift Detection & Correction (Phase 3)
- **FR-3.1**: The system MUST compute windowed cross-correlations across configurable intervals (`--drift-window`) to estimate time-varying offset $offset(t)$.
- **FR-3.2**: The system MUST fit robust linear regression $offset(t) = a + b \cdot t$ and estimate 95% confidence intervals for drift rate $b$ (in ms/hr).
- **FR-3.3**: If drift rate $|b| \ge 50$ ms/hr, the system MUST support signal resampling correction or piecewise linear FCPXML timeline segmentation.

### 1.4 Failure Handling & Robustness (Phase 4)
- **FR-4.1**: Pre-flight checks MUST detect and flag silent audio, clipped audio, missing audio tracks, sample rate mismatches, VFR, long recordings ($>1\text{ hr}$), and non-overlapping windows.

### 1.5 Active Speaker Rough Cut (Phase 5)
- **FR-5.1**: Active Speaker Detection interface MUST operate on the offset-aligned global timeline, merge consecutive same-camera windows, enforce minimum shot duration ($\ge 1.5\text{s}$), and export FCPXML 1.8 timeline.

### 1.6 User Interface (Phase 6)
- **FR-6.1**: The Tkinter GUI (`synccut_gui.py`) MUST display waveform overlays, confidence badges, "Review required" list, manual offset nudge controls ($\pm 100\text{ms}, \pm 10\text{ms}, \pm 1\text{ frame}$), live drift readouts, and direct export for FCPXML, CSV, and PDF reports.
