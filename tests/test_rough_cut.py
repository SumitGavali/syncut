import numpy as np

from synccut.ai import rough_cut
from synccut.config import MIN_SHOT_DURATION_SEC
from synccut.workers.tasks import _single_camera_fallback


def test_rough_cut_holds_current_speaker_until_a_clear_switch(monkeypatch):
    class Detector:
        def __init__(self, _model_path):
            pass

    times = np.arange(0.0, 6.01, 0.5)
    reference = []
    camera_b = []
    for at_time in times:
        reference_confidence = 0.6 if at_time < 4.0 else 0.35
        camera_b_confidence = (
            0.7 if 2.0 <= at_time < 3.5 else 0.95 if at_time >= 4.0 else 0.1
        )
        reference.append((float(at_time), reference_confidence))
        camera_b.append((float(at_time), camera_b_confidence))

    results = {
        "Reference": {"asd_scores": reference, "shot_boundaries": []},
        "Camera B": {"asd_scores": camera_b, "shot_boundaries": []},
    }
    monkeypatch.setattr(rough_cut, "ActiveSpeakerDetector", Detector)
    monkeypatch.setattr(
        rough_cut,
        "analyze_video_source",
        lambda file_path, **kwargs: results[file_path],
    )

    segments = rough_cut.generate_active_speaker_roughcut(
        {
            "Reference": {"file": "Reference", "offset_sec": 0.0},
            "Camera B": {"file": "Camera B", "offset_sec": 0.0},
        }
    )

    assert [segment["camera"] for segment in segments] == ["Reference", "Camera B"]
    assert segments[0]["end"] == 4.5
    assert all(
        segment["end"] - segment["start"] >= MIN_SHOT_DURATION_SEC
        for segment in segments
    )
    assert all("confidence" in segment for segment in segments)


def test_rough_cut_does_not_round_robin_when_no_speaker_is_confident(monkeypatch):
    class Detector:
        def __init__(self, _model_path):
            pass

    scores = [(float(at_time), 0.1) for at_time in np.arange(0.0, 8.0, 0.5)]
    monkeypatch.setattr(rough_cut, "ActiveSpeakerDetector", Detector)
    monkeypatch.setattr(
        rough_cut,
        "analyze_video_source",
        lambda file_path, **kwargs: {
            "asd_scores": scores,
            "shot_boundaries": [],
        },
    )

    segments = rough_cut.generate_active_speaker_roughcut(
        {
            "Reference": {"file": "Reference", "offset_sec": 0.0},
            "Camera B": {"file": "Camera B", "offset_sec": 0.0},
            "Camera C": {"file": "Camera C", "offset_sec": 0.0},
        }
    )

    assert segments == [{
        "camera": "Reference",
        "start": 0.0,
        "end": 7.5,
        "confidence": 0.1,
    }]


def test_rough_cut_ignores_alternating_camera_score_spikes(monkeypatch):
    class Detector:
        def __init__(self, _model_path):
            pass

    times = np.arange(0.0, 8.0, 0.5)
    reference = [(float(t), 0.1) for t in times]
    camera_b = [(float(t), 0.9 if int(t * 2) % 2 == 0 else 0.1) for t in times]
    camera_c = [(float(t), 0.9 if int(t * 2) % 2 == 1 else 0.1) for t in times]
    results = {
        "Reference": {"asd_scores": reference, "shot_boundaries": []},
        "Camera B": {"asd_scores": camera_b, "shot_boundaries": []},
        "Camera C": {"asd_scores": camera_c, "shot_boundaries": []},
    }

    monkeypatch.setattr(rough_cut, "ActiveSpeakerDetector", Detector)
    monkeypatch.setattr(
        rough_cut,
        "analyze_video_source",
        lambda file_path, **kwargs: results[file_path],
    )

    segments = rough_cut.generate_active_speaker_roughcut(
        {
            "Reference": {"file": "Reference", "offset_sec": 0.0},
            "Camera B": {"file": "Camera B", "offset_sec": 0.0},
            "Camera C": {"file": "Camera C", "offset_sec": 0.0},
        }
    )

    assert [segment["camera"] for segment in segments] == ["Camera B"]


def test_empty_ai_result_fallback_uses_one_camera_for_full_duration():
    assert _single_camera_fallback(["Reference", "Camera B", "Camera C"], 61.2) == [
        {
            "camera": "Reference",
            "start": 0.0,
            "end": 61.2,
            "confidence": 0.0,
        }
    ]
