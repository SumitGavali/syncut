import json

from synccut.export import timeline_builder


def test_timeline_export_uses_project_offsets_and_program_lane(monkeypatch, tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "reference.mp4").touch()
    (media_dir / "camera_a.mp4").touch()
    report_path = tmp_path / "sync_report.json"
    report_path.write_text(
        json.dumps(
            {
                "cameras": {
                    "Reference": {
                        "offset_s": 0.0,
                        "drift_ppm": 0.0,
                        "link_confidence": 1.0,
                    },
                    "Camera A": {
                        "offset_s": 1.234,
                        "drift_ppm": 30.0,
                        "link_confidence": 0.95,
                    },
                },
                "loop_error_s": 0.001,
                "results": [
                    {
                        "source": "Reference",
                        "file": "reference.mp4",
                        "offset_s": 0.0,
                        "confidence": 1.0,
                        "status": "Good (reference)",
                    },
                    {
                        "source": "Camera A",
                        "file": "camera_a.mp4",
                        "offset_s": 99.0,
                        "confidence": 0.95,
                        "status": "Good",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(timeline_builder, "get_duration", lambda path: 60.0)

    project = {
        "cameras": [{"source": "Camera A", "offset_s": 1.5}],
        "program": [{
            "camera": "Camera A",
            "start": 2.0,
            "end": 4.0,
            "reason": "Manual angle",
            "source": "manual",
        }],
    }
    timeline = timeline_builder.build_timeline(
        str(report_path), str(media_dir), project=project
    )

    camera_clip = timeline.tracks[1][1]
    assert camera_clip.metadata["synccut"]["offset_s"] == 1.5
    assert camera_clip.metadata["synccut"]["drift_ppm"] == 30.0
    assert timeline.tracks[1][0].duration().to_seconds() == 38 / 25
    program_clip = timeline.tracks[2][1]
    assert program_clip.source_range.start_time.to_seconds() == 12 / 25
    assert program_clip.duration().to_seconds() == 2.0
    assert program_clip.metadata["synccut"] == {
        "camera": "Camera A",
        "reason": "Manual angle",
        "source": "manual",
        "offset_s": 1.5,
    }
    assert timeline.metadata["synccut"]["cameras"]["Camera A"]["offset_s"] == 1.5
