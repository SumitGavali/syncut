# SyncCut Architecture & Module Specification

```
                                ┌───────────────────────────┐
                                │     User Input Media      │
                                │ (2 - 8+ Audio/Video files)│
                                └─────────────┬─────────────┘
                                              │
                                              ▼
                                ┌───────────────────────────┐
                                │       extract.py          │
                                │ (Audio Extraction & SR)   │
                                └─────────────┬─────────────┘
                                              │
                                              ▼
                                ┌───────────────────────────┐
                                │      robustness.py        │
                                │  (Pre-flight Integrity)   │
                                └─────────────┬─────────────┘
                                              │
                                              ▼
                                ┌───────────────────────────┐
                                │      confidence.py        │
                                │  (5-Feature Correlation & │
                                │    Platt/Isotonic Calib)  │
                                └─────────────┬─────────────┘
                                              │
                                              ▼
                                ┌───────────────────────────┐
                                │      sync_engine.py       │
                                │ (Pairwise Matrix, RANSAC, │
                                │  Least Squares Global Fit)│
                                └─────────────┬─────────────┘
                                              │
                                              ▼
                                ┌───────────────────────────┐
                                │         drift.py          │
                                │ (Windowed Fit offset(t),  │
                                │   Drift Resample/Cut)     │
                                └─────────────┬─────────────┘
                                              │
                               ┌──────────────┴──────────────┐
                               ▼                             ▼
               ┌───────────────────────────┐   ┌───────────────────────────┐
               │       rough_cut.py        │   │    timeline_builder.py    │
               │ (Active Speaker ASD & Cut)│   │  (FCPXML & OTIO Export)   │
               └──────────────┬────────────┘   └─────────────┬─────────────┘
                              └──────────────┬───────────────┘
                                             │
                                             ▼
                               ┌───────────────────────────┐
                               │ synccut_gui.py / app.py   │
                               │  (Tkinter UI / Flask Web) │
                               └───────────────────────────┘
```

## Module Responsibilities

- **`config.py`**: Global thresholds, target sample rate ($16000\text{ Hz}$), confidence levels ($0.80/0.40$), drift thresholds ($50\text{ ms/hr}$), and shot duration rules.
- **`extract.py`**: FFmpeg/scipy audio extraction, normalization to 16-bit/float mono $16\text{ kHz}$.
- **`robustness.py`**: Checks for silence, clipping, sample rate mismatch, VFR, missing audio, non-overlapping recordings, and corrupt files.
- **`confidence.py`**: Multi-feature correlation extractor (peak, ratio, FWHM, PSR, SNR), Platt scaling / isotonic regression, ECE & AUC metric calculators, reliability diagrams, and badge assignments.
- **`sync_engine.py`**: Pairwise GCC-PHAT cross-correlation, RANSAC triplet loop inconsistency filter, scipy `least_squares` solver with robust loss (`soft_l1` / `huber`), supporting 2–8+ cameras.
- **`drift.py`**: Windowed offset estimation, robust linear fit $offset(t) = a + b \cdot t$, Student-$t$ 95% confidence intervals, audio resampling, and piecewise FCPXML segment offsets.
- **`rough_cut.py`**: Active Speaker Detection interface (TalkNet adapter + Fallback energy/spectral/diarization heuristic), global timeline alignment, minimum shot duration enforcement, FCPXML 1.8 export.
- **`synccut_gui.py`**: Desktop Tkinter UI with interactive waveform canvas, confidence badges, "Review required" box, manual nudge controls ($\pm 100\text{ms}, \pm 10\text{ms}, \pm 1\text{f}$), drift readout, and PDF/CSV export.
- **`synccut.py`**: CLI wrapper supporting `--sync-mode`, `--drift-correct`, `--drift-window`, `--drift-threshold`, and JSON report output.
