"""
confidence.py — Calibrated confidence scoring for audio synchronization.
Extracts multi-feature metrics from GCC correlation curves, fits calibration models
(Platt scaling / Isotonic Regression), and computes ECE & AUC metrics.
"""
import numpy as np
from scipy.special import expit  # sigmoid function
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import (
    CONFIDENCE_GREEN_THRESHOLD,
    CONFIDENCE_YELLOW_THRESHOLD,
    REVIEW_REQUIRED_THRESHOLD,
)


def extract_correlation_features(cc, fs, peak_idx=None, exclusion_ms=5.0):
    """
    Extract 5 correlation metrics from a cross-correlation curve cc:
    1. primary_peak_val: amplitude of maximum peak
    2. second_peak_ratio: ratio of second-highest peak to primary peak
    3. peak_sharpness: inverse of peak full-width half-max (FWHM) or 3dB width
    4. psr: Peak-to-Sidelobe Ratio = (peak - mean(sidelobes)) / std(sidelobes)
    5. snr_db: 10 * log10(peak^2 / mean(noise_floor^2))
    """
    abs_cc = np.abs(cc)
    if peak_idx is None:
        peak_idx = np.argmax(abs_cc)

    peak_val = float(abs_cc[peak_idx])
    if peak_val <= 1e-12:
        return {
            "primary_peak_val": 0.0,
            "second_peak_ratio": 1.0,
            "peak_sharpness": 0.0,
            "psr": 0.0,
            "snr_db": 0.0,
        }

    # Mask primary peak region for sidelobe / second peak analysis
    exclusion_samples = max(1, int(fs * (exclusion_ms / 1000.0)))
    lo = max(0, peak_idx - exclusion_samples)
    hi = min(len(abs_cc), peak_idx + exclusion_samples + 1)

    sidelobes = abs_cc.copy()
    sidelobes[lo:hi] = 0.0

    second_val = float(sidelobes.max()) if len(sidelobes) > 0 and sidelobes.max() > 0 else 1e-10
    second_peak_ratio = float(np.clip(second_val / peak_val, 0.0, 1.0))

    # Peak width (FWHM - Full Width at Half Maximum)
    half_max = peak_val / 2.0
    left_i = peak_idx
    while left_i > 0 and abs_cc[left_i] > half_max:
        left_i -= 1
    right_i = peak_idx
    while right_i < len(abs_cc) - 1 and abs_cc[right_i] > half_max:
        right_i += 1
    fwhm_samples = max(1, right_i - left_i)
    fwhm_sec = fwhm_samples / float(fs)
    peak_sharpness = float(1.0 / (fwhm_sec + 1e-6))

    # PSR (Peak to Sidelobe Ratio)
    sidelobe_vals = abs_cc[sidelobes > 0]
    if len(sidelobe_vals) > 0:
        mean_side = np.mean(sidelobe_vals)
        std_side = np.std(sidelobe_vals) + 1e-10
        psr = float((peak_val - mean_side) / std_side)
    else:
        psr = 0.0

    # SNR in dB
    noise_power = np.mean(sidelobe_vals ** 2) if len(sidelobe_vals) > 0 else 1e-10
    snr_db = float(10.0 * np.log10((peak_val ** 2) / (noise_power + 1e-12)))

    return {
        "primary_peak_val": peak_val,
        "second_peak_ratio": second_peak_ratio,
        "peak_sharpness": peak_sharpness,
        "psr": psr,
        "snr_db": snr_db,
    }


def compute_heuristic_confidence(features):
    """
    Uncalibrated heuristic confidence combining second peak ratio, PSR, and SNR.
    Fixes old incorrect '1 - (second_peak + primary_peak)' formula.
    """
    sec_score = 1.0 - features["second_peak_ratio"]
    psr_score = np.clip(features["psr"] / 20.0, 0.0, 1.0)
    snr_score = np.clip(features["snr_db"] / 30.0, 0.0, 1.0)
    raw = 0.5 * sec_score + 0.3 * psr_score + 0.2 * snr_score
    return float(np.clip(raw, 0.0, 1.0))


class CalibratedConfidenceScorer:
    """
    Platt Scaling or Isotonic Regression model to convert raw correlation features
    into calibrated probability P(offset error <= 10ms).
    """

    def __init__(self, method="platt"):
        self.method = method
        self.weights = None
        self.bias = None
        self.iso_model = None
        self.is_fitted = False

    def _features_to_vector(self, feat_dict):
        return np.array([
            feat_dict["primary_peak_val"],
            1.0 - feat_dict["second_peak_ratio"],
            np.log1p(feat_dict["peak_sharpness"]),
            feat_dict["psr"],
            feat_dict["snr_db"],
        ])

    def fit(self, feature_dicts, labels):
        """
        Fit Platt scaling (logistic regression) or Isotonic Regression on feature vectors.
        labels: 1 if offset error <= 10ms (or 1 frame), 0 otherwise.
        """
        X = np.array([self._features_to_vector(f) for f in feature_dicts])
        y = np.array(labels, dtype=float)

        if self.method == "platt":
            # Add bias column
            X_b = np.column_stack([np.ones(len(X)), X])
            # Closed-form or ridge logistic solver
            w = np.zeros(X_b.shape[1])
            for _ in range(50):
                p = expit(X_b @ w)
                W_diag = p * (1 - p) + 1e-6
                grad = X_b.T @ (p - y) + 1e-4 * w
                H = (X_b.T * W_diag) @ X_b + 1e-4 * np.eye(len(w))
                w -= np.linalg.solve(H, grad)
            self.bias = w[0]
            self.weights = w[1:]
        elif self.method == "isotonic":
            raw_scores = np.array([compute_heuristic_confidence(f) for f in feature_dicts])
            self.iso_model = IsotonicRegression(out_of_bounds="clip")
            self.iso_model.fit(raw_scores, y)

        self.is_fitted = True

    def predict_proba(self, feat_dict):
        """
        Returns calibrated confidence probability in range [0, 1].
        """
        if not self.is_fitted:
            # Fallback to heuristic score if not fitted
            return compute_heuristic_confidence(feat_dict)

        if self.method == "platt":
            x = self._features_to_vector(feat_dict)
            logit = self.bias + np.dot(self.weights, x)
            return float(expit(logit))
        elif self.method == "isotonic":
            raw = compute_heuristic_confidence(feat_dict)
            return float(self.iso_model.predict([raw])[0])

        return compute_heuristic_confidence(feat_dict)


def compute_ece(probs, labels, n_bins=10):
    """
    Expected Calibration Error (ECE).
    """
    probs = np.array(probs)
    labels = np.array(labels)
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    n = len(probs)

    for i in range(n_bins):
        bin_lower = bin_boundaries[i]
        bin_upper = bin_boundaries[i + 1]
        mask = (probs >= bin_lower) & (probs < bin_upper) if i < n_bins - 1 else (probs >= bin_lower) & (probs <= bin_upper)
        if np.sum(mask) > 0:
            acc = np.mean(labels[mask])
            conf = np.mean(probs[mask])
            ece += (np.sum(mask) / n) * np.abs(acc - conf)

    return float(ece)


def compute_auc(probs, labels):
    """
    Compute Area Under ROC Curve (AUC) for correct vs incorrect offset predictions.
    """
    if len(np.unique(labels)) < 2:
        return 1.0
    return float(roc_auc_score(labels, probs))


def generate_reliability_diagram_plot(probs, labels, save_path="reliability_diagram.png", n_bins=10):
    """
    Generate reliability diagram plot and save to file.
    """
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    accs = []
    confs = []
    counts = []

    probs = np.array(probs)
    labels = np.array(labels)

    for i in range(n_bins):
        bin_lower = bin_boundaries[i]
        bin_upper = bin_boundaries[i + 1]
        mask = (probs >= bin_lower) & (probs < bin_upper) if i < n_bins - 1 else (probs >= bin_lower) & (probs <= bin_upper)
        if np.sum(mask) > 0:
            accs.append(np.mean(labels[mask]))
            confs.append(np.mean(probs[mask]))
            counts.append(np.sum(mask))
        else:
            accs.append(0)
            confs.append((bin_lower + bin_upper) / 2.0)
            counts.append(0)

    bin_centers = (bin_boundaries[:-1] + bin_boundaries[1:]) / 2.0

    plt.figure(figsize=(6, 5))
    plt.bar(bin_centers, accs, width=1.0 / n_bins, alpha=0.6, color="blue", edgecolor="black", label="Outputs")
    plt.plot([0, 1], [0, 1], "r--", label="Ideal Calibration")
    plt.xlabel("Confidence")
    plt.ylabel("Accuracy")
    plt.title("Reliability Diagram")
    plt.legend()
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()
    return save_path


def badge_and_status_from_confidence(conf, drift_ms_per_hr=None):
    """
    Map calibrated confidence float to badge color and status string.
    """
    if conf >= CONFIDENCE_GREEN_THRESHOLD:
        badge = "green"
    elif conf >= CONFIDENCE_YELLOW_THRESHOLD:
        badge = "yellow"
    else:
        badge = "red"

    if conf < REVIEW_REQUIRED_THRESHOLD:
        status = "Review required"
    elif drift_ms_per_hr is not None and abs(drift_ms_per_hr) > 100:
        status = "Corrected (high drift)"
    elif conf < CONFIDENCE_GREEN_THRESHOLD:
        status = "Low confidence"
    else:
        status = "Good"

    return badge, status
