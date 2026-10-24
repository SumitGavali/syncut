"""AI / Active Speaker Detection and rough-cut generation."""

from synccut.ai.rough_cut import (
    ActiveSpeakerDetectorInterface,
    FallbackEnergyDiarizationASD,
    TalkNetASDAdapter,
    generate_active_speaker_roughcut,
    export_roughcut_fcpxml,
)

__all__ = [
    "ActiveSpeakerDetectorInterface",
    "FallbackEnergyDiarizationASD",
    "TalkNetASDAdapter",
    "generate_active_speaker_roughcut",
    "export_roughcut_fcpxml",
]
