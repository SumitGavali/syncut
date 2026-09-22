"""
test_confidence.py — Unit tests for Phase 2 confidence features, calibration, ECE, AUC, and badges.
"""
import pytest
import numpy as np
from confidence import (
    extract_correlation_features,
    compute_heuristic_confidence,
    CalibratedConfidenceScorer,
    compute_ece,
    compute_auc,
    badge_and_status_from_confidence,
)


def test_extract_correlation_features():
    cc = np.zeros(100)
    cc[50] = 1.0  # Sharp main peak
    cc[20] = 0.2  # Secondary peak
    fs = 1000

    feats = extract_correlation_features(cc, fs, peak_idx=50)
    assert feats["primary_peak_val"] == 1.0
    assert abs(feats["second_peak_ratio"] - 0.2) < 0.05
    assert feats["psr"] > 0
    assert feats["snr_db"] > 0


def test_platt_calibration_scorer():
    scorer = CalibratedConfidenceScorer(method="platt")
    dummy_feats = [
        {"primary_peak_val": 1.0, "second_peak_ratio": 0.1, "peak_sharpness": 500, "psr": 30, "snr_db": 40},
        {"primary_peak_val": 0.8, "second_peak_ratio": 0.2, "peak_sharpness": 300, "psr": 20, "snr_db": 25},
        {"primary_peak_val": 0.2, "second_peak_ratio": 0.9, "peak_sharpness": 10,  "psr": 2,  "snr_db": 3},
        {"primary_peak_val": 0.1, "second_peak_ratio": 0.95, "peak_sharpness": 5,  "psr": 1,  "snr_db": 1},
    ]
    labels = [1, 1, 0, 0]

    scorer.fit(dummy_feats, labels)
    prob_good = scorer.predict_proba(dummy_feats[0])
    prob_bad = scorer.predict_proba(dummy_feats[3])

    assert prob_good > prob_bad
    assert 0.0 <= prob_good <= 1.0
    assert 0.0 <= prob_bad <= 1.0


def test_ece_and_auc_metrics():
    probs = [0.9, 0.8, 0.7, 0.2, 0.1]
    labels = [1, 1, 1, 0, 0]

    ece = compute_ece(probs, labels)
    auc = compute_auc(probs, labels)

    assert 0.0 <= ece <= 1.0
    assert auc == 1.0


def test_badge_and_status():
    badge_g, status_g = badge_and_status_from_confidence(0.95)
    assert badge_g == "green"
    assert status_g == "Good"

    badge_r, status_r = badge_and_status_from_confidence(0.20)
    assert badge_r == "red"
    assert status_r == "Review required"
