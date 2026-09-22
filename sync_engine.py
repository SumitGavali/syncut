"""
sync_engine.py — Core GCC-PHAT offset detection and global multi-source solver.
Phase 1: Global multi-source alignment solver with robust loss optimization & RANSAC.
"""
import numpy as np
from scipy.io import wavfile
from scipy.optimize import least_squares

from confidence import extract_correlation_features, compute_heuristic_confidence
from config import TARGET_SR, MAX_TAU_SEC, ROBUST_LOSS, RANSAC_ENABLE, RANSAC_THRESHOLD_SEC


def load_wav(path):
    """Load WAV audio file into float [-1.0, 1.0] mono array."""
    sr, data = wavfile.read(path)
    if data.dtype != np.float32 and data.dtype != np.float64:
        max_val = np.iinfo(data.dtype).max
        data = data.astype(np.float64) / max_val
    if data.ndim > 1:
        data = data.mean(axis=1)
    return sr, data


def gcc_phat(sig1, sig2, fs, max_tau=None, use_phat=True):
    """
    Computes cross-correlation between sig1 and sig2 (using PHAT weighting if use_phat=True).
    Returns (offset_seconds, confidence, cc_curve, features).
    """
    n = sig1.shape[0] + sig2.shape[0]
    SIG1 = np.fft.rfft(sig1, n=n)
    SIG2 = np.fft.rfft(sig2, n=n)
    R = SIG1 * np.conj(SIG2)

    if use_phat:
        denom = np.abs(R)
        denom[denom < 1e-10] = 1e-10
        R /= denom  # Phase Transform (PHAT) normalization

    cc = np.fft.irfft(R, n=n)

    max_shift = int(n / 2)
    if max_tau:
        max_shift = min(int(fs * max_tau), max_shift)

    cc = np.concatenate((cc[-max_shift:], cc[:max_shift + 1]))
    abs_cc = np.abs(cc)

    peak_idx = int(np.argmax(abs_cc))
    features = extract_correlation_features(cc, fs, peak_idx=peak_idx)
    confidence = compute_heuristic_confidence(features)

    shift = peak_idx - max_shift
    offset_seconds = shift / float(fs)

    return offset_seconds, confidence, cc, features


def compute_pairwise_matrix(signals, fs, max_tau=MAX_TAU_SEC, use_phat=True):
    """
    Compute pairwise offset matrix delta[i][j] and weight matrix w[i][j]
    for N sources (where 2 <= N <= 8+).
    delta_ij represents estimated delay: (t_i - t_j).
    """
    N = len(signals)
    delta_matrix = np.zeros((N, N), dtype=float)
    weight_matrix = np.zeros((N, N), dtype=float)
    feature_matrix = {}

    for i in range(N):
        for j in range(i + 1, N):
            offset_ij, conf_ij, _, feats = gcc_phat(
                signals[i], signals[j], fs, max_tau=max_tau, use_phat=use_phat
            )
            delta_matrix[i, j] = offset_ij
            delta_matrix[j, i] = -offset_ij
            weight_matrix[i, j] = conf_ij
            weight_matrix[j, i] = conf_ij
            feature_matrix[(i, j)] = feats
            feature_matrix[(j, i)] = feats

    return delta_matrix, weight_matrix, feature_matrix


def _ransac_filter_pairs(delta_matrix, weight_matrix, N, threshold_sec=RANSAC_THRESHOLD_SEC):
    """
    RANSAC-style outlier rejection for pairwise offsets.
    Checks cycle consistency: delta_ij + delta_jk + delta_ki ≈ 0.
    If a pair (i, j) consistently breaks triplets, reduce its weight.
    """
    w_filtered = weight_matrix.copy()
    inconsistency_scores = np.zeros((N, N), dtype=float)

    for i in range(N):
        for j in range(i + 1, N):
            for k in range(N):
                if k == i or k == j:
                    continue
                # Loop sum = (t_i - t_j) + (t_j - t_k) + (t_k - t_i)
                loop_err = abs(delta_matrix[i, j] + delta_matrix[j, k] + delta_matrix[k, i])
                if loop_err > threshold_sec:
                    inconsistency_scores[i, j] += 1.0
                    inconsistency_scores[j, i] += 1.0

    # Downweight bad pairs
    max_triplets = max(1.0, float(N - 2))
    for i in range(N):
        for j in range(i + 1, N):
            inconsistency_ratio = inconsistency_scores[i, j] / max_triplets
            if inconsistency_ratio > 0.5:
                w_filtered[i, j] = 0.0
                w_filtered[j, i] = 0.0

    return w_filtered


def global_sync_solver(
    delta_matrix,
    weight_matrix,
    ref_index=0,
    loss=ROBUST_LOSS,
    use_ransac=RANSAC_ENABLE,
):
    """
    Solve for global offsets t_i relative to reference camera (t_{ref} = 0)
    by minimizing: sum_ij w_ij * rho(t_i - t_j - delta_ij)
    using scipy.optimize.least_squares.
    """
    N = delta_matrix.shape[0]
    if N <= 1:
        return np.zeros(N, dtype=float)

    w_effective = (
        _ransac_filter_pairs(delta_matrix, weight_matrix, N)
        if use_ransac and N >= 3
        else weight_matrix.copy()
    )

    # Free parameters: offsets for all sources except ref_index (which is fixed to 0.0)
    # Parameter index mapping: map source index i to parameter index
    free_indices = [i for i in range(N) if i != ref_index]

    def residual_func(params):
        # Reconstruct full offset vector t where t[ref_index] = 0
        t = np.zeros(N, dtype=float)
        for idx, free_i in enumerate(free_indices):
            t[free_i] = params[idx]

        residuals = []
        for i in range(N):
            for j in range(i + 1, N):
                w = w_effective[i, j]
                if w > 1e-4:
                    # Residual: sqrt(w) * (t_i - t_j - delta_ij)
                    residuals.append(np.sqrt(w) * (t[i] - t[j] - delta_matrix[i, j]))

        if not residuals:
            return np.zeros(len(free_indices), dtype=float)
        return np.array(residuals, dtype=float)

    x0 = np.zeros(len(free_indices), dtype=float)
    # Initial guess using reference row
    for idx, free_i in enumerate(free_indices):
        x0[idx] = delta_matrix[free_i, ref_index]

    res = least_squares(residual_func, x0, loss=loss)

    t_solved = np.zeros(N, dtype=float)
    for idx, free_i in enumerate(free_indices):
        t_solved[free_i] = float(res.x[idx])

    return t_solved


def solve_multi_source_sync(
    signals,
    fs,
    sync_mode="global",
    ref_index=0,
    max_tau=MAX_TAU_SEC,
    use_phat=True,
    loss=ROBUST_LOSS,
    use_ransac=RANSAC_ENABLE,
):
    """
    High-level entry point supporting both 'global' and 'reference' sync modes.
    Returns:
      global_offsets: array of offsets t_i relative to ref_index
      confidences: list of per-source confidence scores
      feature_dicts: list of feature dicts per source relative to reference
    """
    N = len(signals)
    delta_matrix, weight_matrix, feature_matrix = compute_pairwise_matrix(
        signals, fs, max_tau=max_tau, use_phat=use_phat
    )

    if sync_mode == "global" and N >= 2:
        offsets = global_sync_solver(
            delta_matrix,
            weight_matrix,
            ref_index=ref_index,
            loss=loss,
            use_ransac=use_ransac,
        )
    else:
        # Fallback to reference-only mode: offset_i = delta_{i, ref}
        offsets = np.zeros(N, dtype=float)
        for i in range(N):
            offsets[i] = delta_matrix[i, ref_index]

    confidences = []
    feature_dicts = []
    for i in range(N):
        if i == ref_index:
            confidences.append(1.0)
            feature_dicts.append({
                "primary_peak_val": 1.0,
                "second_peak_ratio": 0.0,
                "peak_sharpness": 1000.0,
                "psr": 50.0,
                "snr_db": 50.0,
            })
        else:
            pair_key = (i, ref_index) if (i, ref_index) in feature_matrix else (ref_index, i)
            feats = feature_matrix.get(pair_key, extract_correlation_features(np.array([1.0]), fs))
            conf = weight_matrix[i, ref_index]
            confidences.append(conf)
            feature_dicts.append(feats)

    return offsets, confidences, feature_dicts
