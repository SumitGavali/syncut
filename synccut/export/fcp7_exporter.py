"""
fcp7_exporter.py — FCP7 XML (xmeml version 4) exporter for SyncCut.
Outputs synchronized multicam sequences compatible with Adobe Premiere Pro.
"""

import json
import math
import os
import xml.dom.minidom
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

from synccut.media.extract import get_duration
from synccut.export.timeline_builder import get_audio_info


def get_rate_parameters(fps: float):
    """
    Computes timebase, ntsc flag, and dropframe flag for a given frame rate.
    
    Standard NTSC timebase mappings:
    - 23.976 / 23.98 fps -> timebase 24, ntsc TRUE
    - 29.97 fps -> timebase 30, ntsc TRUE
    - 59.94 fps -> timebase 60, ntsc TRUE
    - PAL / Film integers: 24, 25, 30, 50, 60 -> timebase = round(fps), ntsc FALSE
    """
    fps_val = float(fps)
    # Check near 23.976
    if abs(fps_val - 23.976) < 0.05 or abs(fps_val - (24000 / 1001)) < 0.01:
        return 24, "TRUE", False
    # Check near 29.97
    elif abs(fps_val - 29.97) < 0.05 or abs(fps_val - (30000 / 1001)) < 0.01:
        return 30, "TRUE", False
    # Check near 59.94
    elif abs(fps_val - 59.94) < 0.05 or abs(fps_val - (60000 / 1001)) < 0.01:
        return 60, "TRUE", False
    else:
        timebase = int(round(fps_val))
        return timebase, "FALSE", False


def _append_rate_subelements(parent: ET.Element, timebase: int, ntsc: str):
    """Helper to append <rate><timebase>...</timebase><ntsc>...</ntsc></rate>."""
    rate_el = ET.SubElement(parent, "rate")
    tb_el = ET.SubElement(rate_el, "timebase")
    tb_el.text = str(timebase)
    ntsc_el = ET.SubElement(rate_el, "ntsc")
    ntsc_el.text = ntsc


def build_xmeml_xml(report_path: str, media_dir: str, fps: float = 25.0, sequence_name: str = "SyncCut Multicam Sequence") -> str:
    """
    Builds an FCP7 XML (xmeml v4) string from sync_report.json and source media files.
    
    Rounding rule comment:
    - Offsets in seconds are converted to timeline frames using:
      frames = round(seconds * fps)
      Standard half-up round is used consistently across timeline in/out and duration
      to guarantee frame boundaries match between video and audio track sync.
    """
    with open(report_path, "r", encoding="utf-8") as f:
        results = json.load(f)

    valid = [r for r in results if r.get("offset_sec") is not None]
    if not valid:
        raise ValueError("No valid synced sources in report — nothing to build.")

    timebase, ntsc, _ = get_rate_parameters(fps)

    # In SyncCut, offset_sec is relative to reference (or global alignment).
    # Positive offset means camera started after reference; negative means camera started before reference.
    # To place all clips on a non-negative timeline where t=0 corresponds to the earliest source start:
    max_offset = max(r["offset_sec"] for r in valid)

    # Prepare clip track data
    sources_to_place = []
    max_timeline_end_frame = 0

    for r in valid:
        file_path = os.path.join(media_dir, r["file"])
        if not os.path.exists(file_path):
            print(f"  WARNING: {file_path} not found, skipping for xmeml export")
            continue

        if r.get("status", "").startswith("FAILED") or r.get("confidence", 1.0) < 0.15:
            print(f"  SKIPPING {r['source']} — confidence below threshold")
            continue

        try:
            duration_sec = get_duration(file_path)
        except Exception:
            duration_sec = 0.0

        if duration_sec <= 0:
            continue

        # In-point trim and timeline placement:
        # Align earliest clip to timeline frame 0.
        trim_in_sec = max(0.0, max_offset - r["offset_sec"])
        remaining_sec = duration_sec - trim_in_sec
        if remaining_sec <= 0:
            continue

        # Rounding rule:
        # round(duration_sec * fps) for source duration
        # round(trim_in_sec * fps) for in-point (source start)
        # round(remaining_sec * fps) for duration on timeline
        file_duration_frames = int(round(duration_sec * fps))
        clip_in_frame = int(round(trim_in_sec * fps))
        clip_duration_frames = int(round(remaining_sec * fps))
        clip_out_frame = clip_in_frame + clip_duration_frames

        # On the timeline, each aligned clip starts at frame 0 (since trim_in_sec handles the lead offset)
        # or at a positive timeline start if offset was lagging behind.
        # Following timeline_builder.py convention: lead audio is trimmed so they all start together at timeline start = 0
        timeline_start_frame = 0
        timeline_end_frame = timeline_start_frame + clip_duration_frames

        if timeline_end_frame > max_timeline_end_frame:
            max_timeline_end_frame = timeline_end_frame

        has_audio, channels, sample_rate = get_audio_info(file_path)
        is_ref = (r.get("source") == "Reference")

        # Create clean file:// URI for pathurl
        abs_path = os.path.abspath(file_path)
        pathurl = Path(abs_path).resolve().as_uri()

        sources_to_place.append({
            "source_label": r["source"],
            "filename": r["file"],
            "file_path": abs_path,
            "pathurl": pathurl,
            "is_ref": is_ref,
            "duration_frames": file_duration_frames,
            "clip_in": clip_in_frame,
            "clip_out": clip_out_frame,
            "timeline_start": timeline_start_frame,
            "timeline_end": timeline_end_frame,
            "has_audio": has_audio,
            "audio_channels": channels or 2,
            "audio_rate": sample_rate or 48000
        })

    if not sources_to_place:
        raise ValueError("No sources could be placed on the timeline.")

    # ── Root <xmeml version="4"> ──
    xmeml = ET.Element("xmeml", version="4")
    sequence = ET.SubElement(xmeml, "sequence")
    
    # Sequence Metadata
    name_el = ET.SubElement(sequence, "name")
    name_el.text = sequence_name

    duration_el = ET.SubElement(sequence, "duration")
    duration_el.text = str(max_timeline_end_frame)

    _append_rate_subelements(sequence, timebase, ntsc)

    timecode_el = ET.SubElement(sequence, "timecode")
    _append_rate_subelements(timecode_el, timebase, ntsc)
    tc_string = ET.SubElement(timecode_el, "string")
    tc_string.text = "00:00:00:00"
    tc_frame = ET.SubElement(timecode_el, "frame")
    tc_frame.text = "0"
    tc_display = ET.SubElement(timecode_el, "displayformat")
    tc_display.text = "NDF"

    media_el = ET.SubElement(sequence, "media")
    video_el = ET.SubElement(media_el, "video")
    
    # Video format
    vformat_el = ET.SubElement(video_el, "format")
    sample_characteristics = ET.SubElement(vformat_el, "samplecharacteristics")
    _append_rate_subelements(sample_characteristics, timebase, ntsc)
    w_el = ET.SubElement(sample_characteristics, "width")
    w_el.text = "1920"
    h_el = ET.SubElement(sample_characteristics, "height")
    h_el.text = "1080"
    anamorphic_el = ET.SubElement(sample_characteristics, "anamorphic")
    anamorphic_el.text = "FALSE"
    pixel_aspect = ET.SubElement(sample_characteristics, "pixelaspectratio")
    pixel_aspect.text = "square"

    audio_el = ET.SubElement(media_el, "audio")
    aformat_el = ET.SubElement(audio_el, "format")
    a_sample_characteristics = ET.SubElement(aformat_el, "samplecharacteristics")
    depth_el = ET.SubElement(a_sample_characteristics, "depth")
    depth_el.text = "16"
    samplerate_el = ET.SubElement(a_sample_characteristics, "samplerate")
    samplerate_el.text = "48000"

    # Separate reference from cameras
    ref_sources = [s for s in sources_to_place if s["is_ref"]]
    cam_sources = [s for s in sources_to_place if not s["is_ref"]]

    # ── Video Tracks ──
    # One video track per camera
    file_id_counter = 1
    clip_id_counter = 1

    for idx, cam in enumerate(cam_sources, start=1):
        vtrack = ET.SubElement(video_el, "track")
        clipitem = ET.SubElement(vtrack, "clipitem", id=f"clipitem-video-{clip_id_counter}")
        clip_id_counter += 1

        cname = ET.SubElement(clipitem, "name")
        cname.text = f"{cam['source_label']} - {cam['filename']}"

        cdur = ET.SubElement(clipitem, "duration")
        cdur.text = str(cam["duration_frames"])

        _append_rate_subelements(clipitem, timebase, ntsc)

        cin = ET.SubElement(clipitem, "in")
        cin.text = str(cam["clip_in"])

        cout = ET.SubElement(clipitem, "out")
        cout.text = str(cam["clip_out"])

        cstart = ET.SubElement(clipitem, "start")
        cstart.text = str(cam["timeline_start"])

        cend = ET.SubElement(clipitem, "end")
        cend.text = str(cam["timeline_end"])

        # <file id="...">
        file_el = ET.SubElement(clipitem, "file", id=f"file-{file_id_counter}")
        cam["file_id"] = f"file-{file_id_counter}"
        file_id_counter += 1

        fname_el = ET.SubElement(file_el, "name")
        fname_el.text = cam["filename"]

        fpath_el = ET.SubElement(file_el, "pathurl")
        fpath_el.text = cam["pathurl"]

        _append_rate_subelements(file_el, timebase, ntsc)

        fdur_el = ET.SubElement(file_el, "duration")
        fdur_el.text = str(cam["duration_frames"])

        fmedia = ET.SubElement(file_el, "media")
        fvideo = ET.SubElement(fmedia, "video")
        fsample = ET.SubElement(fvideo, "samplecharacteristics")
        _append_rate_subelements(fsample, timebase, ntsc)
        ET.SubElement(fsample, "width").text = "1920"
        ET.SubElement(fsample, "height").text = "1080"

        if cam["has_audio"]:
            faudio = ET.SubElement(fmedia, "audio")
            faudio_sample = ET.SubElement(faudio, "samplecharacteristics")
            ET.SubElement(faudio_sample, "depth").text = "16"
            ET.SubElement(faudio_sample, "samplerate").text = str(cam["audio_rate"])
            ET.SubElement(faudio, "channelcount").text = str(cam["audio_channels"])

    # ── Audio Tracks ──
    # Requirement: The reference audio on its own audio track; one audio track per camera.
    # We place Reference audio track first (A1), followed by Camera audio tracks (A2, A3, ...).
    audio_order = ref_sources + cam_sources

    for src in audio_order:
        atrack = ET.SubElement(audio_el, "track")
        clipitem = ET.SubElement(atrack, "clipitem", id=f"clipitem-audio-{clip_id_counter}")
        clip_id_counter += 1

        cname = ET.SubElement(clipitem, "name")
        cname.text = f"{src['source_label']} - {src['filename']}"

        cdur = ET.SubElement(clipitem, "duration")
        cdur.text = str(src["duration_frames"])

        _append_rate_subelements(clipitem, timebase, ntsc)

        cin = ET.SubElement(clipitem, "in")
        cin.text = str(src["clip_in"])

        cout = ET.SubElement(clipitem, "out")
        cout.text = str(src["clip_out"])

        cstart = ET.SubElement(clipitem, "start")
        cstart.text = str(src["timeline_start"])

        cend = ET.SubElement(clipitem, "end")
        cend.text = str(src["timeline_end"])

        # Re-use existing file id if already declared in video, else declare file
        file_id = src.get("file_id") or f"file-{file_id_counter}"
        file_el = ET.SubElement(clipitem, "file", id=file_id)
        if "file_id" not in src:
            src["file_id"] = file_id
            file_id_counter += 1

        fname_el = ET.SubElement(file_el, "name")
        fname_el.text = src["filename"]

        fpath_el = ET.SubElement(file_el, "pathurl")
        fpath_el.text = src["pathurl"]

        _append_rate_subelements(file_el, timebase, ntsc)

        fdur_el = ET.SubElement(file_el, "duration")
        fdur_el.text = str(src["duration_frames"])

        fmedia = ET.SubElement(file_el, "media")
        faudio = ET.SubElement(fmedia, "audio")
        faudio_sample = ET.SubElement(faudio, "samplecharacteristics")
        ET.SubElement(faudio_sample, "depth").text = "16"
        ET.SubElement(faudio_sample, "samplerate").text = str(src["audio_rate"])
        ET.SubElement(faudio, "channelcount").text = str(src["audio_channels"])

        # Source track mapping: map channel 1 to audio track output
        sourcetrack = ET.SubElement(clipitem, "sourcetrack")
        ET.SubElement(sourcetrack, "mediatype").text = "audio"
        ET.SubElement(sourcetrack, "trackindex").text = "1"

    # Pretty-print xml
    raw_xml = ET.tostring(xmeml, encoding="utf-8")
    reparsed = xml.dom.minidom.parseString(raw_xml)
    # Return formatted XML with proper doctype
    xml_header = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
    # minidom toprettyxml adds <?xml ...?>, so we extract root
    pretty_xml = reparsed.documentElement.toprettyxml(indent="  ")
    return xml_header + pretty_xml


def export_fcp7_xml(report_path: str, media_dir: str, output_path: str, fps: float = 25.0):
    """Generates and writes FCP7 XML (xmeml v4) to output_path."""
    xml_content = build_xmeml_xml(report_path, media_dir, fps=fps)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
    print(f"Exported FCP7 XML (xmeml v4) to: {output_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export synced sequence as FCP7 XML (xmeml v4) for Premiere Pro")
    parser.add_argument("--report", required=True, help="Path to sync_report.json")
    parser.add_argument("--media-dir", required=True, help="Folder containing source media files")
    parser.add_argument("--output", required=True, help="Output path (.xml)")
    parser.add_argument("--fps", type=float, default=25.0, help="Timeline frame rate (e.g. 23.976, 25, 29.97)")
    args = parser.parse_args()

    export_fcp7_xml(args.report, args.media_dir, args.output, fps=args.fps)
