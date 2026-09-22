"""
test_global_sync.py — Unit tests for Phase 1 global multi-source solver.
"""
import pytest
import numpy as np
from sync_engine import global_sync_solver, solve_multi_source_sync


def test_global_sync_solver_ideal_triplet():
    # 3 sources with true offsets: t_0 = 0, t_1 = 0.5, t_2 = 1.2
    # delta_ij = t_i - t_j
    t_true = np.array([0.0, 0.5, 1.2])
    N = 3
    delta_matrix = np.zeros((N, N))
    weight_matrix = np.ones((N, N))

    for i in range(N):
        for j in range(N):
            delta_matrix[i, j] = t_true[i] - t_true[j]

    t_solved = global_sync_solver(delta_matrix, weight_matrix, ref_index=0)
    np.testing.assert_allclose(t_solved, t_true, atol=1e-5)


def test_global_sync_solver_with_outlier_ransac():
    # 4 sources with true offsets: [0.0, 0.3, 0.8, -0.4]
    t_true = np.array([0.0, 0.3, 0.8, -0.4])
    N = 4
    delta_matrix = np.zeros((N, N))
    weight_matrix = np.ones((N, N))

    for i in range(N):
        for j in range(N):
            delta_matrix[i, j] = t_true[i] - t_true[j]

    # Corrupt pair (1, 2) with a huge outlier: delta_12 should be -0.5, set to +5.0
    delta_matrix[1, 2] = 5.0
    delta_matrix[2, 1] = -5.0
    weight_matrix[1, 2] = 0.9
    weight_matrix[2, 1] = 0.9

    t_solved = global_sync_solver(delta_matrix, weight_matrix, ref_index=0, use_ransac=True)
    # The solver should reject the outlier pair (1, 2) and recover t_true accurately
    np.testing.assert_allclose(t_solved, t_true, atol=0.05)


def test_solve_multi_source_sync_synthetic_signals():
    fs = 8000
    dur = 2.0
    t = np.linspace(0, dur, int(fs * dur))
    base_sig = np.sin(2 * np.pi * 440 * t) + np.random.normal(0, 0.05, len(t))

    shift_samples_1 = int(fs * 0.1)  # 100 ms shift
    shift_samples_2 = int(fs * 0.25) # 250 ms shift

    sig0 = base_sig
    sig1 = np.pad(base_sig, (shift_samples_1, 0))[:len(base_sig)]
    sig2 = np.pad(base_sig, (shift_samples_2, 0))[:len(base_sig)]

    signals = [sig0, sig1, sig2]
    offsets, confidences, _ = solve_multi_source_sync(signals, fs, sync_mode="global")

    assert len(offsets) == 3
    assert abs(offsets[0]) < 0.01
    assert abs(offsets[1] - 0.1) < 0.02
    assert abs(offsets[2] - 0.25) < 0.02
