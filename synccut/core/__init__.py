"""Core math/audio: GCC-PHAT sync, drift, confidence, robustness, energy switching."""

from synccut.core.sync_engine import (
    load_wav,
    gcc_phat,
    compute_pairwise_matrix,
    global_sync_solver,
    solve_multi_source_sync,
)
from synccut.core.drift import (
    windowed_offsets,
    analyze_drift,
    correct_audio_drift_resample,
    generate_piecewise_drift_offsets,
    create_drift_report,
)
from synccut.core.confidence import (
    extract_correlation_features,
    compute_heuristic_confidence,
    CalibratedConfidenceScorer,
    compute_ece,
    compute_auc,
    generate_reliability_diagram_plot,
    badge_and_status_from_confidence,
)
from synccut.core.robustness import (
    RobustnessError,
    check_file_readable,
    analyze_audio_quality,
    check_sample_rates,
    check_recording_duration,
    check_overlap,
    preflight_media_check,
)
from synccut.core.camera_switch import (
    analyze_audio_energy,
    generate_camera_switches,
    generate_switch_timeline,
    print_switch_summary,
)

__all__ = [
    # sync_engine
    "load_wav",
    "gcc_phat",
    "compute_pairwise_matrix",
    "global_sync_solver",
    "solve_multi_source_sync",
    # drift
    "windowed_offsets",
    "analyze_drift",
    "correct_audio_drift_resample",
    "generate_piecewise_drift_offsets",
    "create_drift_report",
    # confidence
    "extract_correlation_features",
    "compute_heuristic_confidence",
    "CalibratedConfidenceScorer",
    "compute_ece",
    "compute_auc",
    "generate_reliability_diagram_plot",
    "badge_and_status_from_confidence",
    # robustness
    "RobustnessError",
    "check_file_readable",
    "analyze_audio_quality",
    "check_sample_rates",
    "check_recording_duration",
    "check_overlap",
    "preflight_media_check",
    # camera_switch
    "analyze_audio_energy",
    "generate_camera_switches",
    "generate_switch_timeline",
    "print_switch_summary",
]
