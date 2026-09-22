"""
config.py — Configuration parameters and thresholds for SyncCut.
"""
import os

# Default Target Audio Parameters
TARGET_SR = 16000
MAX_TAU_SEC = 30.0

# Sync Mode Defaults
DEFAULT_SYNC_MODE = "global"  # 'global' or 'reference'
ROBUST_LOSS = "soft_l1"       # 'huber', 'soft_l1', 'cauchy', etc.
RANSAC_ENABLE = True
RANSAC_THRESHOLD_SEC = 0.05   # 50 ms outlier threshold for RANSAC

# Confidence Thresholds & Calibration
CONFIDENCE_GREEN_THRESHOLD = 0.80
CONFIDENCE_YELLOW_THRESHOLD = 0.40
REVIEW_REQUIRED_THRESHOLD = 0.40

# Drift Thresholds
DEFAULT_DRIFT_WINDOW_SEC = 30.0
DEFAULT_DRIFT_MIN_WINDOWS = 3
DRIFT_CORRECT_THRESHOLD_MS_PER_HR = 50.0  # correct drift if > 50 ms/hr

# Audio Analysis Thresholds
MIN_AUDIO_ENERGY_DB = -60.0
CLIPPING_THRESHOLD_RATIO = 0.05
MAX_SILENCE_RATIO = 0.95

# Camera Switch & Active Speaker Constraints
MIN_SHOT_DURATION_SEC = 1.5
SWITCH_WINDOW_SEC = 0.5
