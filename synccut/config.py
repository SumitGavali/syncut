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
SYNC_LOCKED_PSR = 8.0
SYNC_VERIFY_PSR = 3.0
SYNC_LOCKED_WINDOW_STD_MS = 2.0
SYNC_VERIFY_WINDOW_STD_MS = 12.0
SYNC_LOCKED_LOOP_ERROR_MS = 2.0
SYNC_VERIFY_LOOP_ERROR_MS = 15.0
SYNC_MASTER_TIE_MARGIN = 0.01
SYNC_WAVEFORM_RATE = 100

# Drift Thresholds
DEFAULT_DRIFT_WINDOW_SEC = 30.0
DEFAULT_DRIFT_MIN_WINDOWS = 3
DRIFT_CORRECT_THRESHOLD_MS_PER_HR = 50.0  # correct drift if > 50 ms/hr

TASK_SOFT_TIME_LIMIT = int(os.environ.get("SYNC_TASK_SOFT_TIME_LIMIT", "14400"))
TASK_TIME_LIMIT = int(os.environ.get("SYNC_TASK_TIME_LIMIT", "15000"))

# Audio Analysis Thresholds
MIN_AUDIO_ENERGY_DB = -60.0
CLIPPING_THRESHOLD_RATIO = 0.05
MAX_SILENCE_RATIO = 0.95

# Camera Switch & Active Speaker Constraints
MIN_SHOT_DURATION_SEC = 1.5
SWITCH_WINDOW_SEC = 0.5
