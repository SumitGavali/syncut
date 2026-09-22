"""
export_switch_timeline.py — Exports camera-switch segments as a real,
importable edit timeline.

Replaces the original export_switch_edl.py, which hand-wrote a text file
shaped like an EDL but with raw-seconds timestamps instead of HH:MM:SS:FF
timecode and no CMX3600 edit-type fields — that file would not reliably
import into Resolve/Premiere. This version builds a proper OpenTimelineIO
timeline (one video track, sequential clips cut from each camera's own
source file at the right in/out points) and exports through the same
FCPXML path already fixed and verified in timeline_builder.py — including
the library/event wrapper and the <audio> component patches.
"""
import json
import os
import opentimelineio as otio
from extract import get_duration
from timeline_builder import export_timeline  # reuse the verified, patched export


def build_switch_timeline(switches_path, media_dir, fps=25.0, name="synccut_rough_cut"):
    """
    Build a single-track rough-cut timeline: one clip per switch segment,
    cut from the corresponding camera's own source file.
    """
    with open(switches_path) as f:
        segments = json.load(f)

    if not segments:
        raise ValueError("No switch segments to build a timeline from.")

    timeline = otio.schema.Timeline(name=name)
    track = otio.schema.Track(name="Rough Cut", kind=otio.schema.TrackKind.Video)

    for seg in segments:
        file_path = os.path.join(media_dir, seg["file"])
        if not os.path.exists(file_path):
            print(f"  WARNING: {file_path} not found, skipping segment {seg['start_sec']}-{seg['end_sec']}s")
            continue

        duration_sec = get_duration(file_path)
        start_sec = max(0.0, seg["start_sec"])
        end_sec = min(duration_sec, seg["end_sec"])
        clip_duration = end_sec - start_sec
        if clip_duration <= 0:
            continue

        media_ref = otio.schema.ExternalReference(
            target_url=__import__("pathlib").Path(file_path).resolve().as_uri(),
            available_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, fps),
                duration=otio.opentime.RationalTime(round(duration_sec * fps), fps)
            )
        )
        clip = otio.schema.Clip(
            name=f"{seg['camera']} ({seg['file']})",
            media_reference=media_ref,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(round(start_sec * fps), fps),
                duration=otio.opentime.RationalTime(round(clip_duration * fps), fps)
            )
        )
        track.append(clip)
        print(f"  {seg['camera']}: {start_sec:.1f}s - {end_sec:.1f}s ({clip_duration:.1f}s)")

    timeline.tracks.append(track)
    return timeline


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build an importable rough-cut timeline from camera switch segments")
    parser.add_argument("--switches", required=True, help="camera_switches.json from camera_switch.py")
    parser.add_argument("--media-dir", required=True, help="Folder containing original video files")
    parser.add_argument("--output", default="rough_cut.fcpxml", help="Output path (.fcpxml)")
    parser.add_argument("--fps", type=float, default=25.0, help="Project frame rate")
    args = parser.parse_args()

    print("Building rough-cut timeline from camera switches...")
    tl = build_switch_timeline(args.switches, args.media_dir, fps=args.fps)
    export_timeline(tl, args.output)