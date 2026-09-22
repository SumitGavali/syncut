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
from extract import get_duration


def build_timeline(report_path, media_dir, fps=25.0, name="synccut_timeline"):
    """Build an OTIO timeline from a sync report."""
    with open(report_path) as f:
        results = json.load(f)

    timeline = otio.schema.Timeline(name=name)

    valid = [r for r in results if r.get("offset_sec") is not None]
    if not valid:
        raise ValueError("No valid synced sources in report — nothing to build.")

    max_offset = max(r["offset_sec"] for r in valid)

    for r in valid:
        file_path = os.path.join(media_dir, r["file"])
        if not os.path.exists(file_path):
            print(f"  WARNING: {file_path} not found, skipping track for {r['source']}")
            continue

        if r["status"].startswith("FAILED") or r["confidence"] < 0.15:
            print(f"  SKIPPING {r['source']} — status: {r['status']} (below confidence threshold, needs manual review)")
            continue

        track = otio.schema.Track(name=r["source"], kind=otio.schema.TrackKind.Video)

        duration_sec = get_duration(file_path)
        trim_in_sec = max(0.0, max_offset - r["offset_sec"])
        remaining_duration = duration_sec - trim_in_sec

        if remaining_duration <= 0:
            print(f"  WARNING: {r['source']} too short after trim, skipping")
            continue

        media_ref = otio.schema.ExternalReference(
            target_url=Path(file_path).resolve().as_uri(),
            available_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, fps),
                duration=otio.opentime.RationalTime(round(duration_sec * fps), fps)
            )
        )

        clip = otio.schema.Clip(
            name=r["file"],
            media_reference=media_ref,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(round(trim_in_sec * fps), fps),
                duration=otio.opentime.RationalTime(round(remaining_duration * fps), fps)
            )
        )
        track.append(clip)
        timeline.tracks.append(track)

        conf_pct = round(r["confidence"] * 100)
        print(f"  {r['source']}: trimmed {trim_in_sec:.3f}s in, confidence {conf_pct}%, status: {r['status']}")

    return timeline


def get_audio_info(file_path):
    """Returns (has_audio, channels, sample_rate) via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a:0",
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
        _add_audio_components(output_path)   # FIXED: now correctly maps Asset ID -> Channels
        _wrap_with_library_event(output_path)

    print(f"\nExported: {output_path}")


# ---------- PATCH FUNCTIONS ----------

def _fix_asset_audio_attributes(fcpxml_path):
    """
    For each <asset>, read the actual source file and add/update:
        audioSources="1" audioChannels="X" audioRate="Y"
    """
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
    """
    FIXED: Now properly maps Asset ID -> audioChannels.
    For each <video> tag, looks up the asset ID to get channel count,
    and adds a matching <audio> sibling with audioChannelSource.
    """
    with open(fcpxml_path, "r", encoding="utf-8") as f:
        content = f.read()

    # --- STEP 1: Build a map of Asset ID -> Channel Count ---
    asset_channels = {}
    # Find all asset tags that have an 'id' and 'audioChannels'
    for match in re.finditer(r'<asset\b[^>]*id="([^"]+)"[^>]*audioChannels="([^"]+)"[^>]*/>', content):
        asset_id = match.group(1)
        channels = int(match.group(2))
        asset_channels[asset_id] = channels

    # If for some reason audioChannels is missing in the asset tag (shouldn't happen after _fix_asset),
    # we fall back to probing, but we'll rely on the tag to avoid redundant ffprobe calls.

    # --- STEP 2: Replace each <video> with <video> + <audio> ---
    def add_audio_sibling(match):
        video_tag = match.group(0)
        ref_match = re.search(r'ref="([^"]+)"', video_tag)
        if not ref_match:
            return video_tag

        asset_id = ref_match.group(1)
        channels = asset_channels.get(asset_id, 0)

        # If this asset has no audio, just return the video tag unchanged
        if channels == 0:
            return video_tag

        # Extract offset and duration from the video tag
        offset_match = re.search(r'offset="([^"]+)"', video_tag)
        offset = offset_match.group(1) if offset_match else "0s"
        duration_match = re.search(r'duration="([^"]+)"', video_tag)
        duration = duration_match.group(1) if duration_match else "0s"

        # Build the audioChannelSource string: e.g., "1" for mono, "1,2" for stereo, "1,2,3,4" for quad
        channel_source = ",".join(str(i) for i in range(1, channels + 1))

        audio_tag = f'<audio offset="{offset}" ref="{asset_id}" duration="{duration}" audioChannelSource="{channel_source}" role="dialogue"/>'
        return f"{video_tag}\n                    {audio_tag}"

    # Apply the replacement to all self-closing video tags
    content = re.sub(r'<video\b[^>]*/>', add_audio_sibling, content)

    with open(fcpxml_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("  Patched FCPXML: added <audio> components with correct audioChannelSource.")


def _wrap_with_library_event(fcpxml_path):
    """Wrap <project> in <library>/<event> for Resolve."""
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