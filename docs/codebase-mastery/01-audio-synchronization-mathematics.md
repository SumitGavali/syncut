# Order 1 — Audio Synchronization Mathematics

This is the foundation document. Everything else in SyncCut Studio exists on top of the
idea explained here: **if two cameras recorded the same room, their audio contains the
same signal, shifted in time — and a computer can measure that shift.**

Grounded in the actual code:

- [../../synccut/core/sync_core.py](../../synccut/core/sync_core.py) — the production engine
- [../../synccut/core/sync_engine.py](../../synccut/core/sync_engine.py) — GCC-PHAT reference engine
- [../../synccut/core/confidence.py](../../synccut/core/confidence.py) — confidence scoring
- [../../synccut/core/drift.py](../../synccut/core/drift.py) — drift measurement/correction
- [../../synccut/core/robustness.py](../../synccut/core/robustness.py) — pre-flight checks
- [../../synccut/media/extract.py](../../synccut/media/extract.py) — decode to a common format
- [../../synccut/media/mixdown.py](../../synccut/media/mixdown.py) — build the master mixdown
- [../../synccut/config.py](../../synccut/config.py) — every threshold used here

---

## 1. The problem, from scratch

### 1.1 What a digital audio signal actually is

A microphone turns air pressure into a voltage. An ADC samples that voltage at a fixed rate.
The result is a list of numbers:

```
x[0], x[1], x[2], ... x[N-1]
```

Each number is the pressure at time `n / fs`, where `fs` is the **sample rate**.

SyncCut standardises on **`fs = 16000` Hz** (`TARGET_SR` in
[config.py](../../synccut/config.py)). So sample `n` is at time `n / 16000` seconds, and one
sample is `1/16000 = 0.0000625` s = **62.5 microseconds**. That is the finest resolution the
system can represent before interpolation.

### 1.2 Why two cameras see the same signal with a delay

Two phones recording the same room both capture the same claps, speech, and music. But:

- **Start time differs** — one is pressed 4.3 s before the other.
- **Position differs** — the sound reaches one mic slightly earlier (sub-millisecond), which
  is negligible compared to start-time differences.
- **Clock speeds differ** — a cheap crystal might run 0.003 % fast, which drifts by seconds
  over an hour. This is **drift**.

So the two recordings are approximately:

```
camera_a[n] ~= s[n]
camera_b[n] ~= s[n - k]        (k = the lag, in samples)
```

If we can find `k` for every camera, we can place every camera on one shared timeline. That
is literally the whole product.

### 1.3 Why we cannot just "look at the waveform"

Audio is oscillatory. A 440 Hz tone repeats every 2.27 ms. Matching peak-to-peak would give
you thousands of equally good answers. We need a statistic that is **high at exactly one lag**.

---

## 2. Cross-correlation — the core tool

### 2.1 The formula

The cross-correlation of `x` and `y` at lag `k` is:

```
            N-1
(x ⋆ y)[k] = SUM  x[n] * conj(y[n - k])
            n=0
```

In words: slide `y` by `k` samples, multiply point-by-point with `x`, and sum. When the two
signals line up, the products are all positive and the sum is large. When they do not, the
products cancel.

### 2.2 Why FFT is used

Direct evaluation is `O(N²)`. The convolution theorem says:

```
x ⋆ y  =  IFFT( FFT(x) * conj(FFT(y)) )
```

That is `O(N log N)`. For a 10-minute record at 16 kHz that is 9.6 million samples — the
difference between minutes and hours of CPU time.

You can see both engines using `method="fft"` in
[sync_core.py](../../synccut/core/sync_core.py) and `np.fft.rfft` / `np.fft.irfft` in
[sync_engine.py](../../synccut/core/sync_engine.py).

### 2.3 Simple numerical example

```
x = [0, 0, 1, 2, 1, 0, 0]
y = [1, 2, 1, 0, 0, 0, 0]
```

`y` is `x` shifted left by 2. Cross-correlating and looking for the peak returns lag `k = 2`.
Divide by `fs` to get seconds.

### 2.4 Converting lag to an offset — and the sign trap

This is where most bugs live. SyncCut is explicit:

> **`offset = reference_time − camera_time`** (verified in
> `_local_offsets()` in [sync_core.py](../../synccut/core/sync_core.py))

A **positive offset means the reference leads the camera** — i.e. the camera's recording
started *later* (or equivalently, that camera's content is *behind*). Extra derivations:

- `offset_samples = round(offset_s * 16000)`
- `offset_ms = offset_s * 1000`
- `offset_frames = round(offset_s * fps)` (25 fps in the default project)

Two engines, one convention. `sync_engine.gcc_phat()` returns `shift / fs` where a positive
shift means `sig1` leads `sig2` — the same "first argument leads" rule.

---

## 3. GCC-PHAT — the sharper tool

### 3.1 The problem with plain cross-correlation

Plain correlation weights loud frequency bands more. A hum, a fan, or a bass rumble can
dominate and smear the peak.

### 3.2 What PHAT does

GCC-PHAT replaces the magnitude spectrum with 1, keeping only the phase:

```
R = FFT(x) * conj(FFT(y))
R /= |R|                      # PHAT weighting
cc = IFFT(R)
```

Because every frequency contributes equally to the phase, the peak becomes much sharper and
far less sensitive to frequency-dependent loudness. Implemented in
`gcc_phat()` in [sync_engine.py](../../synccut/core/sync_engine.py):

```python
SIG1 = np.fft.rfft(sig1, n=n)
SIG2 = np.fft.rfft(sig2, n=n)
R = SIG1 * np.conj(SIG2)
if use_phat:
    mag = np.abs(R)
    mag[mag < 1e-10] = 1e-10        # floor avoids divide-by-zero
    R = R / mag
cc = np.fft.irfft(R, n=n)
```

The `1e-10` floor matters: silent bins would otherwise produce `0/0 = NaN` and poison the
whole inverse transform.

### 3.3 Sub-sample accuracy

Frames are 40 ms apart at 25 fps, but audio lag is measured to **62.5 µs**. That mismatch is
why the code uses **parabolic interpolation** around the correlation peak:

```python
fractional_peak = peak + 0.5 * (left - right) / (left - 2*center + right)
```

This fits a parabola through three points and returns its vertex, giving sub-sample lag
resolution. `sync_engine` relies on the raw grid plus a max-lag bound; `sync_core` adds this
interpolation.

---

## 4. The two engines — and which one actually runs

There are **two synchronization implementations**. This is the single most confusing part of
the codebase, so it is stated plainly:

| | `sync_engine.py` | `sync_core.py` |
|---|---|---|
| Nickname | legacy / GCC-PHAT reference | fast / production |
| Correlation | GCC-PHAT on whole signals | plain FFT cross-correlation on 8 s windows |
| Outlier handling | RANSAC triplet-consistency + `soft_l1` robust loss | weighted least squares, confidence weights |
| Drift | separate module (`drift.py`) | built in, per-window regression |
| Memory | loads full signals | memmaps, 10 s chunks |
| Sub-sample | grid only | parabolic interpolation |
| Selected when | `SYNC_ENGINE=legacy` | default (`SYNC_ENGINE` unset/"fast") |

The dispatch lives in `solve_multi_source_sync()` in
[sync_engine.py](../../synccut/core/sync_engine.py):

```python
if (
    os.environ.get("SYNC_ENGINE", "fast").strip().lower() != "legacy"
    and N > 1
    and min(len(s) for s in signals) >= 16 * fs
):
    from synccut.core.sync_core import sync_arrays
    return sync_arrays(...)
```

So: **for real footage (longer than 16 s) the fast engine runs by default.** `sync_engine.py`
remains the mathematical reference and the RANSAC/robust fallback.

---

## 5. The production pipeline, step by step

Entry points in [sync_core.py](../../synccut/core/sync_core.py):

- `sync_arrays(arrays, names, sample_rate, progress_callback, cancel_check)` — in-memory
- `sync_files(file_paths, cache_dir, ...)` — same, but decodes first (concurrently)

### Stage 0 — Decode to a common format (`_decode_one`)

```
ffmpeg -i <file> -vn -ac 1 -ar 16000 -c:a pcm_s16le -af highpass=f=80 <out>
```

- **mono** (`-ac 1`) — one channel, because correlation needs a single series
- **16 kHz** (`-ar 16000`) — the project standard `TARGET_SR`
- **s16le PCM** — raw, un-compressed, easy to memmap
- **80 Hz high-pass** — removes rumble, HVAC hum and handling noise that corrupt the envelope

Results are cached under `<session>/_sync_audio/` keyed by SHA-256 of
`(abspath, size, mtime)`. A file with **no audio stream** gets silence of the video's
duration and is marked `WEAK`.

### Stage 1 — Coarse offset (`_coarse_offset`)

Full-length correlation is memory-hungry, so SyncCut first collapses each signal to a
**100 Hz RMS envelope** (`_envelope`) and correlates those:

```python
ref_env = _envelope(reference, sample_rate)     # 100 Hz
cam_env = _envelope(camera, sample_rate)
corr = signal.correlate(ref_env, cam_env, mode="full", method="fft")
lags = signal.correlation_lags(len(ref_env), len(cam_env), mode="full")
```

Search is bounded by `MAX_TAU_SEC = 30.0`, so `|lag| <= 30 * 100 = 3000` envelope samples.
The envelope is decimated by 160× (16 kHz / 100 Hz), which is cheap and robust to phase
inversion — it finds *roughly* where to look.

### Stage 2 — Windowed refinement (`_local_offsets`)

Now the engine slides an **8-second window** across the reference, spaced roughly every 10 s,
capped at **80 windows**:

```python
window = min(8 * fs, len(ref)//2, len(cam)//2)
n_windows = min(80, max(1, int(span / (10.0 * fs))))
```

For each window it correlates the reference chunk against a **wider** camera chunk
(`+2 s` margin on each side, predicted by the coarse offset), mean-subtracts both, and takes
the correlation peak with parabolic interpolation. Each window yields a tuple:

```
(ref_time, offset, confidence, psr)
```

This is what makes the system robust on long recordings: instead of one global guess, it
collects many local measurements, so drift, a truck passing, or a phone being picked up
only corrupts a few windows.

### Stage 3 — Fit per pair (`_fit_offset`)

For each camera pair, the window observations become a weighted linear regression:

```
offset(t) = intercept + slope * t
```

Weight = `max(confidence, 1e-3)`. `intercept` becomes that pair's offset; `slope` becomes its
drift. Returned as `(intercept, slope, confidence, psr, window_std_s)`.

### Stage 4 — Choose the master (`sync_arrays`)

Not the first file — the **cleanest** one:

1. Compute per-signal strength (std of 1 s-decimated audio).
2. `usable = [i for i where strength >= 1e-5]`.
3. Master = the usable camera with the highest **mean pair confidence**.
4. Ties within `SYNC_MASTER_TIE_MARGIN = 0.01` go to the first, for deterministic output.

This is verified by two tests in
[tests/test_sync_core.py](../../tests/test_sync_core.py):
- `test_silent_reference_is_weak_and_audible_camera_becomes_master`
- `test_cleanest_audio_becomes_master_even_when_first_camera_is_audible`

### Stage 5 — Global least squares (`sync_arrays`)

Every pairwise intercept is one equation. With the master pinned at 0:

```
offset_j - offset_i = intercept_ij        for every measured pair (i, j)
```

Assembled as a sparse-ish matrix and solved with weights = `max(confidence, 1e-3)`:

```python
solution = np.linalg.lstsq(matrix * sqrt(w), values * sqrt(w))
```

The same solve is repeated for drift slopes. This is why SyncCut is described as a
**global** solver: a camera that pairs badly with the master but pairs well with two others
still gets placed correctly, because all edges vote.

### Stage 6 — Loop-closure error

If `A→B`, `B→C` and `C→A` disagree, the geometry is inconsistent. SyncCut measures exactly
that:

```
loop_error = weighted_RMS( intercept_ij - (offset_j - offset_i) )
```

returned as `loop_error_s`. It is a genuine integrity signal, not decoration.

### Stage 7 — Classify each camera

From `config.py`:

| State | Condition (all must hold) |
|---|---|
| `LOCKED` | `psr >= 8.0` and `window_std_ms <= 2.0` and `loop_error_ms <= 2.0` |
| `VERIFY` | `psr >= 3.0` and `window_std_ms <= 12.0` and `loop_error_ms <= 15.0` |
| `WEAK` | anything else |

A drift above **5 ppm** logs a warning.

---

## 6. The legacy GCC-PHAT path (still worth understanding)

`sync_engine.py` is the textbook implementation and is easier to reason about.

### `gcc_phat(sig1, sig2, fs, max_tau, use_phat)` -> `(offset_s, confidence, cc, features)`

1. `n = len(sig1) + len(sig2)`; `R = FFT(sig1) * conj(FFT(sig2))`
2. PHAT-normalise `R`
3. `cc = IFFT(R)`
4. Restrict to `|lag| <= fs * max_tau`, reorder negatives-then-positives
5. `peak = argmax(|cc|)`, `shift = peak - max_shift`, `offset = shift / fs`

### `compute_pairwise_matrix(signals, fs, ...)`

Builds `delta[i,j] = t_i - t_j` and a symmetric confidence weight matrix. This is the
pairwise graph.

### `global_sync_solver(delta, weights, ref_index, loss="soft_l1", use_ransac=True)`

1. `_ransac_filter_pairs` — for each pair, count triplets `(i,j,k)` violating
   `|delta_ij + delta_jk + delta_ki| > RANSAC_THRESHOLD_SEC (0.05 s)`; if a pair breaks more
   than half its triplets, its weight is zeroed.
2. `scipy.optimize.least_squares` with **soft-L1** robust loss, minimising
   `sqrt(w) * (t_i - t_j - delta_ij)`.
3. Returns absolute offsets relative to `ref_index`.

Verified by [tests/test_global_sync.py](../../tests/test_global_sync.py):

- `test_global_sync_solver_ideal_triplet` — exact recovery, `atol=1e-5`
- `test_global_sync_solver_with_outlier_ransac` — a corrupted pair `delta[1,2] = +5.0` (truth
  `-0.5`) is rejected and the solve still lands within `0.05 s`

**Trade-off in one line:** robust loss + RANSAC survives badly-corrupted pairs; plain
weighted least squares is faster and simpler and is what the fast engine uses.

---

## 7. Confidence — is this answer trustworthy?

### 7.1 Features (`extract_correlation_features`)

From a correlation curve, five features are extracted (exclusion zone = **5 ms** around the
peak):

| Feature | Meaning |
|---|---|
| `primary_peak_val` | height of the best peak |
| `second_peak_ratio` | second-best peak / best peak — high means ambiguous |
| `peak_sharpness` | `1 / FWHM_seconds` — sharp is good |
| `psr` | peak-to-sidelobe ratio `(peak − mean(sidelobe)) / std(sidelobe)` |
| `snr_db` | `10 * log10(peak² / mean(sidelobe²))` |

### 7.2 Heuristic score (`compute_heuristic_confidence`)

```
sec_score = 1 - second_peak_ratio
psr_score = clip(psr / 20.0, 0, 1)
snr_score = clip(snr_db / 30.0, 0, 1)
confidence = 0.5*sec_score + 0.3*psr_score + 0.2*snr_score
```

Unambiguous match dominates (0.5), then peak sharpness (0.3), then loudness (0.2).

### 7.3 Calibration (`CalibratedConfidenceScorer`)

The heuristic is a hand-tuned score, not a probability. The class learns a real probability:

- **Platt scaling** — logistic regression trained by 50 iterations of IRLS with L2 `1e-4`,
  features `[primary_peak_val, 1−second_peak_ratio, log1p(peak_sharpness), psr, snr_db]`
- **Isotonic** — `sklearn.isotonic.IsotonicRegression(out_of_bounds="clip")`

Labels are `1` when the offset error is `<= 10 ms`. Quality is then measured honestly with
**ECE** (`compute_ece`) and **AUC** (`compute_auc`).

### 7.4 Badges and status

Thresholds from [config.py](../../synccut/config.py):

| Confidence | Badge | Status string |
|---|---|---|
| `>= 0.80` | green | `Good` |
| `>= 0.40` | yellow | `Low confidence` |
| `< 0.40` | red | `Review required` |

Plus a special case: drift `> 100 ms/hr` produces `Corrected (high drift)`. Verified in
[tests/test_confidence.py](../../tests/test_confidence.py).

---

## 8. Drift — when clocks do not run at the same speed

### 8.1 Detection (`windowed_offsets` + `analyze_drift`)

in [drift.py](../../synccut/core/drift.py):

- Window `DEFAULT_DRIFT_WINDOW_SEC = 30.0`, hop = 50 % of window
- Adaptive hop keeps the count near ≤ 20 windows so CPU stays bounded
- Windows with `confidence < min_confidence` (`0.3`) are discarded
- Require at least `DEFAULT_DRIFT_MIN_WINDOWS = 3` reliable windows

Then ordinary least squares `slope, intercept = np.polyfit(times, offsets, 1)`, with a 95 %
confidence interval from the Student-t distribution (`n-2` degrees of freedom):

```
slope_se = sqrt(residual_variance / sum((t - mean(t))²))
ci = slope ± t_value * slope_se
```

Converted to human units by multiplying by `3_600_000` (seconds/second -> ms/hour).
Drift is declared significant at `DRIFT_CORRECT_THRESHOLD_MS_PER_HR = 50.0`.

Verified: `test_analyze_drift_linear_synthetic` recovers a true `100 ms/hr` slope within
`15 ms/hr`.

### 8.2 Correction (two ways)

1. **Resample** (`correct_audio_drift_resample`) — Fourier resample by `1+slope` to physically
   stretch the audio; `|slope| < 1e-8` is a no-op.
2. **Piecewise offsets** (`generate_piecewise_drift_offsets`) — keep the audio untouched and
   emit per-segment offsets, which matters for **video**, where you cannot resample a face.
   Default segment length `10.0 s`.

This is the design insight worth remembering: **audio can be resampled, video cannot — so the
product corrects video by moving cut points, not pixels.**

---

## 9. Pre-flight checks (`robustness.py`)

Cheap checks that stop a bad job before it burns CPU:

| Check | Rule | Constant |
|---|---|---|
| Unreadable file | missing / 0 bytes | — |
| Silent | `max|x| < 1e-7` or RMS `< -60 dB` | `MIN_AUDIO_ENERGY_DB = -60.0` |
| Mostly silent | zero-sample ratio `> 0.95` | `MAX_SILENCE_RATIO = 0.95` |
| Clipped | `|x| > 0.99` for `> 5 %` of samples | `CLIPPING_THRESHOLD_RATIO = 0.05` |
| Sample-rate mismatch | rates differ | — |
| Long recording | `>= 3600 s` | — |
| No overlap | overlap `<= 1.0 s` | — |

All covered by
[tests/robustness/test_failure_cases.py](../../tests/robustness/test_failure_cases.py).

---

## 10. The master mixdown (`mixdown.py`)

`build_master_mixdown(wav_paths, offsets, out_path, target_sr=16000)` turns N aligned camera
stems into **one audio track** that the browser plays while the video cuts between cameras.

Algorithm:

1. `min_off = min(0, *offsets)` — the earliest start becomes timeline zero.
2. `starts[i] = (offset_i - min_off) * sr` — each stem's sample position.
3. `total = max(start_i + len(sig_i))` — output length.
4. Process in **10-second chunks** (memory safety). For each chunk, each signal is mapped to
   timeline positions with **linear interpolation** (`left + (right-left)*fraction`) so
   sub-sample alignment survives.
5. Sum the contributions, then **divide by the number of signals** (average, not peak
   normalise), clip to `[-1, 1]`, scale to int16, write with the `wave` module.

Why average instead of peak-normalise: peak normalisation would make a quiet 8-camera
mixdown blast at full scale whenever one mic clipped. Averaging keeps the loudness honest.

Returned to the UI as `master_audio_url = /api/session/<id>/master_audio`.

---

## 11. Non-AI camera switching (`camera_switch.py`)

Before the AI existed, SyncCut chose cameras by **audio energy**:

- `analyze_audio_energy(path, trim_in_sec, window_sec=0.5)` — RMS per 0.5 s window, in dB
- `generate_camera_switches(report_path, media_dir, window_sec=0.5, min_energy_db=-40, min_shot_sec=1.5)`

Key correctness detail: energy is compared **at the same real-world moment** using the sync
offsets, via `trim_in = max(0, max_offset - offset_sec)`. Without that, you would compare
camera A's t=10 s against camera B's t=10 s even though they are different real moments —
the classic multicam bug. If nobody exceeds `-40 dB`, the previous camera is held (no
flicker), and shots shorter than `1.5 s` are absorbed.

This module is the honest fallback origin story for the AI path in
[rough_cut.py](../../synccut/ai/rough_cut.py), which keeps the same hold-and-absorb
philosophy.

---

## 12. How accuracy is measured (`eval/evaluate_sync.py`)

The benchmark harness computes, per method and per dataset:

| Metric | Definition |
|---|---|
| **MAE (ms)** | mean absolute error vs ground-truth offsets |
| **Success@10ms** | fraction of cameras within 10 ms (sub-frame) |
| **Success@1frame** | fraction within 40 ms (one frame at 25 fps) |
| **ECE** | calibration error of the confidence score |
| **AUC** | how well confidence separates good from bad |
| **RTF** | compute time / signal duration (must be `< 1` to be "real time") |
| **Peak memory (MB)** | via `tracemalloc` |

Methods compared: `synccut_global_phat`, `baseline_reference_only`,
`ablation_without_phat`, `ablation_without_global_solver`. Synthetic ground truth uses
`[0.0, 0.050, 0.120, -0.080] s`. This is an ablation study, not just a demo — it is how the
team can prove which part of the pipeline earns its keep.

---

## 13. Check your understanding

1. Why does the fast engine decimate to a 100 Hz envelope before correlating? What would
   break if it correlated full-band audio across a 30-minute recording?
2. `offset = ref_time - camera_time`. Camera B starts 2 s *after* camera A, and A is the
   master. What is B's `offset_s`? In which direction does the master mixdown shift B?
3. Two cameras disagree: A→B says 1.000 s, B→C says 1.000 s, C→A says 2.100 s. Which of
   `psr`, `window_std_ms`, `loop_error_ms` will flag this, and which state results?
4. Why is the master a **least-squares** choice rather than "the first file"?
5. Drift is `+120 ms/hr`. Why can the system fix video without resampling pixels?
