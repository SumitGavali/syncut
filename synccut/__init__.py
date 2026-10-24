"""SyncCut — multi-camera audio sync and multimedia suite."""

from synccut.config import (
    TARGET_SR,
    DEFAULT_SYNC_MODE,
    DEFAULT_DRIFT_WINDOW_SEC,
    DRIFT_CORRECT_THRESHOLD_MS_PER_HR,
)

__version__ = "2.0.0"

__all__ = [
    "__version__",
    "TARGET_SR",
    "DEFAULT_SYNC_MODE",
    "DEFAULT_DRIFT_WINDOW_SEC",
    "DRIFT_CORRECT_THRESHOLD_MS_PER_HR",
]
