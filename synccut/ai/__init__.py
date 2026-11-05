# src/synccut/ai/__init__.py

from synccut.ai.rough_cut import (
    generate_active_speaker_roughcut,
    export_roughcut_fcpxml,
)

# If you have a class in face_tracker.py you want to expose, add it here:
from synccut.ai.face_tracker import ActiveSpeakerDetector

__all__ = [
    "generate_active_speaker_roughcut",
    "export_roughcut_fcpxml",
    "ActiveSpeakerDetector",
]