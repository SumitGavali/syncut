"""
timeline_builder.py — turns a sync report (offsets) into an actual editable
timeline file (.edl / .fcpxml) that Premiere, Resolve, or Final Cut can open.
"""
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse, unquote

import opentimelineio as otio
from synccut.media.extract import get_duration


def build_timeline(report_path, media_dir, fps=25.0, name="synccut_timeline", project=None):
    """Build an OTIO timeline from a sync report."""
    with open(report_path) as f:
        report = json.load(f)
    if isinstance(report, dict):
        results = report.get("results", [])
        cameras = report.get("cameras", {})
    else:
        results = report
        cameras = {}
    results = [
        {
            **row,
            "offset_s": cameras.get(row.get("source"), {}).get(
                "offset_s", row.get("offset_s", row.get("offset_sec"))
            ),
            "drift_ppm": cameras.get(row.get("source"), {}).get(
                "drift_ppm", row.get("drift_ppm", 0.0)
            ),
        }
        for row in results
    ]
    project = project if isinstance(project, dict) else {}
    project_cameras = {
        row.get("source"): row
        for row in project.get("cameras", [])
        if isinstance(row, dict) and row.get("source")
    }
    cameras = {
        **cameras,
        **{
            source: {
                **cameras.get(source, {}),
                "offset_s": row.get("offset_s", cameras.get(source, {}).get("offset_s")),
            }
            for source, row in project_cameras.items()
        },
    }
    results = [
        {
            **row,
            "offset_s": project_cameras.get(row.get("source"), {}).get(
                "offset_s", row.get("offset_s")
            ),
        }
        for row in results
    ]

    timeline = otio.schema.Timeline(name=name)
    timeline.global_start_time = otio.opentime.RationalTime(0, fps)

    valid = [r for r in results if r.get("offset_s") is not None]
    if not valid:
        raise ValueError("No valid synced sources in report — nothing to build.")

    timeline_origin = min(r["offset_s"] for r in valid)
    timeline.metadata["synccut"] = {
        "cameras": cameras,
        "loop_error_s": report.get("loop_error_s", 0.0) if isinstance(report, dict) else 0.0,
        "master_source": report.get("master_source") if isinstance(report, dict) else None,
        "program": project.get("program", []),
    }

    media_by_source = {}
    for r in valid:
        file_path = os.path.join(media_dir, r["file"])
        if not os.path.exists(file_path):
            print(f"  WARNING: {file_path} not found, skipping track for {r['source']}")
            continue

        duration_sec = float(r.get("duration_sec") or get_duration(file_path))
        if duration_sec <= 0:
            continue

        track = otio.schema.Track(
            name=r["source"], 
            kind=otio.schema.TrackKind.Video,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, fps),
                duration=otio.opentime.RationalTime(round(duration_sec * fps), fps)
            )
        )

        timeline_start_sec = max(0.0, r["offset_s"] - timeline_origin)

        media_ref = otio.schema.ExternalReference(
            target_url=Path(file_path).resolve().as_uri(),
            available_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, fps),
                duration=otio.opentime.RationalTime(round(duration_sec * fps), fps)
            )
        )

        if timeline_start_sec > 0:
            track.append(otio.schema.Gap(
                source_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(0, fps),
                    duration=otio.opentime.RationalTime(round(timeline_start_sec * fps), fps),
                )
            ))
        clip = otio.schema.Clip(
            name=r["file"],
            media_reference=media_ref,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, fps),
                duration=otio.opentime.RationalTime(round(duration_sec * fps), fps)
            ),
        )
        clip.metadata["synccut"] = {
            "offset_s": r["offset_s"],
            "drift_ppm": r.get("drift_ppm", 0.0),
            "state": r.get("state", "VERIFY"),
            "psr": r.get("psr"),
        }
        track.append(clip)
        timeline.tracks.append(track)
        media_by_source[r["source"]] = (r, file_path, duration_sec, media_ref)

    program = project.get("program", [])
    if program:
        program_track = otio.schema.Track(
            name="PROGRAM",
            kind=otio.schema.TrackKind.Video,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, fps),
                duration=otio.opentime.RationalTime(0, fps)
            )
        )
        cursor = 0.0
        
        first_segment = sorted(program, key=lambda item: float(item.get("start", 0)))[0]
        first_start = max(0.0, float(first_segment.get("start", 0)) - timeline_origin)
        
        if first_start > 0:
            program_track.append(otio.schema.Gap(
                source_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(0, fps),
                    duration=otio.opentime.RationalTime(round(first_start * fps), fps),
                )
            ))
            cursor = first_start

        for segment in sorted(program, key=lambda item: float(item.get("start", 0))):
            source = media_by_source.get(segment.get("camera"))
            if not source:
                continue
            row, file_path, source_duration, media_ref = source
            start = max(float(segment.get("start", 0)), float(row["offset_s"]))
            end = min(float(segment.get("end", start)), float(row["offset_s"]) + source_duration)
            if end <= start:
                continue
            timeline_start = max(0.0, start - timeline_origin)
            timeline_end = max(timeline_start, end - timeline_origin)
            
            if timeline_start > cursor:
                program_track.append(otio.schema.Gap(
                    source_range=otio.opentime.TimeRange(
                        start_time=otio.opentime.RationalTime(0, fps),
                        duration=otio.opentime.RationalTime(round((timeline_start - cursor) * fps), fps),
                    )
                ))
            clip = otio.schema.Clip(
                name=f"{segment.get('camera', 'Camera')} — {segment.get('reason', 'Program cut')}",
                media_reference=media_ref,
                source_range=otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(round((start - row["offset_s"]) * fps), fps),
                    duration=otio.opentime.RationalTime(round((end - start) * fps), fps),
                ),
            )
            clip.metadata["synccut"] = {
                "camera": segment.get("camera"),
                "reason": segment.get("reason"),
                "source": segment.get("source", "manual"),
                "offset_s": row["offset_s"],
            }
            program_track.append(clip)
            cursor = timeline_end

        if len(program_track):
            program_track.source_range = otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, fps),
                duration=otio.opentime.RationalTime(round(cursor * fps), fps)
            )
            timeline.tracks.append(program_track)

    return timeline


def get_audio_info(file_path):
    """Returns (has_audio, channels, sample_rate) via ffprobe."""
    from synccut.paths import get_ffprobe_path
    cmd = [
        get_ffprobe_path(), "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=channels,sample_rate",
        "-of", "default=noprint_wrappers=1", file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = result.stdout.strip()
    if not out:
        return False, None, None

    values = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()

    try:
        channels = int(values.get("channels", 2))
        sample_rate = int(values.get("sample_rate", 48000))
        return True, channels, sample_rate
    except ValueError:
        return True, 2, 48000


def export_timeline(timeline, output_path):
    """Export to FCPXML (or other) and apply required patches."""
    otio.adapters.write_to_file(timeline, output_path)

    if output_path.lower().endswith(".fcpxml"):
        _fix_asset_audio_attributes(output_path)
        _add_audio_components(output_path)
        _wrap_with_library_event(output_path)

    print(f"\nExported: {output_path}")


# ---------- PATCH FUNCTIONS ----------

def _fix_asset_audio_attributes(fcpxml_path):
    with open(fcpxml_path, "r", encoding="utf-8") as f:
        content = f.read()

    def update_asset(match):
        asset_tag = match.group(0)
        src_match = re.search(r'src="([^"]+)"', asset_tag)
        if not src_match:
            return asset_tag

        file_url = src_match.group(1)
        file_path = unquote(urlparse(file_url).path)
        if re.match(r"^/[A-Za-z]:", file_path):
            file_path = file_path[1:]

        has_audio, channels, sample_rate = get_audio_info(file_path)
        if not has_audio:
            asset_tag = re.sub(r'hasAudio="[01]"', 'hasAudio="0"', asset_tag)
            asset_tag = re.sub(r'audioSources="[^"]*"', '', asset_tag)
            asset_tag = re.sub(r'audioChannels="[^"]*"', '', asset_tag)
            asset_tag = re.sub(r'audioRate="[^"]*"', '', asset_tag)
            return asset_tag

        asset_tag = re.sub(r'hasAudio="[01]"', 'hasAudio="1"', asset_tag)
        if 'audioSources="' not in asset_tag:
            asset_tag = asset_tag.replace('hasAudio="1"', 'hasAudio="1" audioSources="1"')
        if 'audioChannels="' not in asset_tag:
            asset_tag = asset_tag.replace('audioSources="1"', f'audioSources="1" audioChannels="{channels}"')
        if 'audioRate="' not in asset_tag:
            asset_tag = asset_tag.replace(f'audioChannels="{channels}"', f'audioChannels="{channels}" audioRate="{sample_rate}"')
        return asset_tag

    content = re.sub(r"<asset\b[^>]*/>", update_asset, content)

    with open(fcpxml_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("  Patched FCPXML: asset audio attributes updated.")


def _add_audio_components(fcpxml_path):
    with open(fcpxml_path, "r", encoding="utf-8") as f:
        content = f.read()

    asset_channels = {}
    for match in re.finditer(r'<asset\b[^>]*id="([^"]+)"[^>]*audioChannels="([^"]+)"[^>]*/>', content):
        asset_id = match.group(1)
        channels = int(match.group(2))
        asset_channels[asset_id] = channels

    def add_audio_sibling(match):
        video_tag = match.group(0)
        ref_match = re.search(r'ref="([^"]+)"', video_tag)
        if not ref_match:
            return video_tag

        asset_id = ref_match.group(1)
        channels = asset_channels.get(asset_id, 0)

        if channels == 0:
            return video_tag

        offset_match = re.search(r'offset="([^"]+)"', video_tag)
        offset = offset_match.group(1) if offset_match else "0s"
        duration_match = re.search(r'duration="([^"]+)"', video_tag)
        duration = duration_match.group(1) if duration_match else "0s"

        channel_source = ",".join(str(i) for i in range(1, channels + 1))

        audio_tag = f'<audio offset="{offset}" ref="{asset_id}" duration="{duration}" audioChannelSource="{channel_source}" role="dialogue"/>'
        return f"{video_tag}\n                    {audio_tag}"

    content = re.sub(r'<video\b[^>]*/>', add_audio_sibling, content)

    with open(fcpxml_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("  Patched FCPXML: added <audio> components with correct audioChannelSource.")


def _wrap_with_library_event(fcpxml_path):
    with open(fcpxml_path, "r", encoding="utf-8") as f:
        content = f.read()

    if "<library" in content:
        return

    match = re.search(r"(<project.*?</project>)", content, re.DOTALL)
    if not match:
        print("  WARNING: could not find <project> block to wrap — Resolve import may still fail.")
        return

    project_block = match.group(1)
    wrapped = f'<library>\n<event name="SyncCut Import">\n{project_block}\n</event>\n</library>'
    content = content.replace(project_block, wrapped)

    with open(fcpxml_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("  Patched FCPXML: wrapped <project> in required <library>/<event> hierarchy for Resolve.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build editable timeline from sync report")
    parser.add_argument("--report", required=True, help="sync_report.json from synccut.py")
    parser.add_argument("--media-dir", required=True, help="Folder containing original video files")
    parser.add_argument("--output", required=True, help="Output path (.edl, .fcpxml, or .otio)")
    parser.add_argument("--fps", type=float, default=25.0, help="Project frame rate")
    args = parser.parse_args()

    print("Building timeline from sync report...")
    tl = build_timeline(args.report, args.media_dir, fps=args.fps)
    export_timeline(tl, args.output)