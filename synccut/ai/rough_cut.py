import os
import subprocess
import logging
from typing import Dict, List, Any

import cv2
import numpy as np
import librosa

from synccut.ai.face_tracker import ActiveSpeakerDetector
from synccut.config import MIN_SHOT_DURATION_SEC

logger = logging.getLogger(__name__)

# WHY: If histogram difference is > 0.4, it's a hard cut / motion blur.
SHOT_BOUNDARY_THRESHOLD = 0.4
SPEAKER_CONFIDENCE_THRESHOLD = 0.3
SPEAKER_SWITCH_MARGIN = 0.15
SPEAKER_SWITCH_CONFIRMATION_STEPS = 2

# Face detection runs on a downscaled copy of each frame (much faster on CPU).
DETECT_WIDTH = 640
# Light-ASD expects 25 video frames and 100 MFCC frames per window.
ASD_FPS = 25.0
MFCC_HOP = 160  # 16000 Hz / 100 MFCC frames per second


def calculate_frame_difference(frame1, frame2) -> float:
    """
    WHY: We use Histograms instead of pixel-by-pixel comparison because
    histograms are immune to slight camera shakes, but will spike
    drastically on a hard cut or a flash.
    """
    hist1 = cv2.calcHist([frame1], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    hist2 = cv2.calcHist([frame2], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    cv2.normalize(hist1, hist1, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    cv2.normalize(hist2, hist2, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    correlation = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
    return 1.0 - correlation


def analyze_video_source(
    file_path: str,
    offset_sec: float,
    detector: ActiveSpeakerDetector,
    cancel_check=None,
    progress_callback=None,
) -> Dict[str, Any]:
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        logger.error(f"Could not open video: {file_path}")
        return {"asd_scores": [], "shot_boundaries": []}

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    if video_fps == 0 or video_fps > 120:
        video_fps = ASD_FPS
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None

    # Extract full audio for this video to get MFCC features
    temp_wav = f"temp_audio_{os.getpid()}_{abs(hash(file_path))}.wav"
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-i', file_path, '-vn', '-acodec', 'pcm_s16le',
             '-ar', '16000', '-ac', '1', temp_wav],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        audio, sr = librosa.load(temp_wav, sr=16000)
        # 100 MFCC frames per second -> 4 per video frame at 25 fps
        mfcc = librosa.feature.mfcc(y=audio, sr=sr, n_mfcc=13, hop_length=MFCC_HOP)
        mfcc = mfcc.T  # (Time, 13)
    except Exception as e:
        logger.error(f"Audio extraction failed for {file_path}: {e}")
        cap.release()
        return {"asd_scores": [], "shot_boundaries": []}
    finally:
        if os.path.exists(temp_wav):
            os.remove(temp_wav)

    asd_scores = []
    shot_boundaries = []
    frame_count = 0
    frame_buffer = []
    name = os.path.basename(file_path)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        video_time = frame_count / video_fps
        timeline_time = video_time + offset_sec

        # Downscale BEFORE face detection: big speed-up on CPU.
        h, w = frame.shape[:2]
        if w > DETECT_WIDTH:
            scale = DETECT_WIDTH / float(w)
            small = cv2.resize(frame, (DETECT_WIDTH, int(h * scale)))
        else:
            small = frame
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = detector.detect_faces(small)

        face_crop = np.zeros((112, 112), dtype=np.uint8)
        if len(faces) > 0:
            (x, y, fw, fh) = max(faces, key=lambda f: f[2] * f[3])
            crop = gray[y:y + fh, x:x + fw]
            if crop.size > 0:
                face_crop = cv2.resize(crop, (112, 112))

        frame_buffer.append(face_crop)

        if len(frame_buffer) == 25:
            if cancel_check:
                cancel_check()
            if progress_callback:
                # tasks.py finds the camera by looking for the basename in this text
                progress_callback(frame_count, total_frames, f"Analyzing {name}")

            # Audio window aligned to these 25 frames (4 MFCC steps per frame)
            audio_start = max(0, (frame_count - 24) * 4)
            audio_window = mfcc[audio_start:audio_start + 100]
            if audio_window.shape[0] < 100:
                pad = np.zeros((100 - audio_window.shape[0], 13))
                audio_window = np.vstack((audio_window, pad)) if audio_window.size else pad

            vis_input = np.expand_dims(np.array(frame_buffer), axis=0)  # (1, 25, 112, 112)
            aud_input = np.expand_dims(audio_window, axis=0)            # (1, 100, 13)

            probs = detector.predict_speaking_sequence(vis_input, aud_input)

            for i, prob in enumerate(probs):
                t = timeline_time - (24 - i) / video_fps
                if t >= 0:
                    asd_scores.append((t, float(prob)))

            frame_buffer = []

        frame_count += 1

    cap.release()
    return {"asd_scores": asd_scores, "shot_boundaries": shot_boundaries}


def generate_active_speaker_roughcut(
    sources_data: Dict[str, dict],
    fs: int = 16000,
    cancel_check=None,
    progress_callback=None,
) -> List[dict]:
    """
    Iterates all cameras, finds who is talking, and generates segments.

    sources_data format:
    {"Camera A": {"file": "path/to/camA.mp4", "offset_sec": 0.0}, ...}
    """
    model_path = os.path.join(os.path.dirname(__file__), "models", "light_asd.onnx")
    detector = ActiveSpeakerDetector(model_path)

    all_asd_data = {}
    all_boundaries = []

    # --- PHASE 1: Analyze all videos ---
    for cam_name, data in sources_data.items():
        logger.info(f"Analyzing visual AI for {cam_name}...")
        result = analyze_video_source(
            file_path=data["file"],
            offset_sec=data["offset_sec"],
            detector=detector,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
        )
        all_asd_data[cam_name] = result["asd_scores"]
        all_boundaries.extend(result["shot_boundaries"])

    # --- PHASE 2: Generate the Timeline (State Machine) ---
    if not all_asd_data:
        return []

    all_times = [t for scores in all_asd_data.values() for t, _ in scores]
    if not all_times:
        return []
    start_time = min(all_times)
    end_time = max(all_times)

    segments = []
    current_camera = None
    segment_start = start_time
    pending_camera = None
    pending_camera_steps = 0
    confidence_totals = {}
    confidence_counts = {}

    def close_segment(end_t):
        if current_camera is None or end_t <= segment_start:
            return
        count = confidence_counts.get(current_camera, 0)
        mean_confidence = (
            confidence_totals.get(current_camera, 0.0) / count if count else 0.0
        )
        segments.append({
            "camera": current_camera,
            "start": round(segment_start, 2),
            "end": round(end_t, 2),
            "confidence": round(mean_confidence, 4),
        })

    score_series = {}
    for camera, scores in all_asd_data.items():
        ordered = sorted(scores, key=lambda score: score[0])
        score_series[camera] = (
            np.asarray([score[0] for score in ordered], dtype=np.float64),
            np.asarray([score[1] for score in ordered], dtype=np.float32),
        )

    def score_at(camera, at_time):
        times, confidences = score_series[camera]
        if not len(times):
            return 0.0
        index = int(np.searchsorted(times, at_time))
        candidates = [i for i in (index - 1, index) if 0 <= i < len(times)]
        if not candidates:
            return 0.0
        nearest = min(candidates, key=lambda i: abs(times[i] - at_time))
        if abs(times[nearest] - at_time) >= 1.0:
            return 0.0
        return float(confidences[nearest])

    current_time = start_time
    while current_time < end_time:
        camera_confidences = {
            camera: score_at(camera, current_time) for camera in all_asd_data
        }
        highest_camera = max(camera_confidences, key=camera_confidences.get, default=None)
        highest_conf = (
            camera_confidences.get(highest_camera, 0.0) if highest_camera is not None else 0.0
        )

        current_conf = camera_confidences.get(current_camera, 0.0)
        best_cam = current_camera
        if highest_camera is not None and highest_conf >= SPEAKER_CONFIDENCE_THRESHOLD:
            if current_camera is None or current_conf < SPEAKER_CONFIDENCE_THRESHOLD:
                best_cam = highest_camera
            elif highest_camera != current_camera and highest_conf >= (
                current_conf + SPEAKER_SWITCH_MARGIN
            ):
                best_cam = highest_camera
        elif current_camera is None:
            best_cam = next(iter(sources_data), None)

        is_near_boundary = any(abs(b - current_time) < 0.5 for b in all_boundaries)

        if current_camera is None:
            current_camera = best_cam
            segment_start = current_time
        elif best_cam == current_camera:
            pending_camera = None
            pending_camera_steps = 0
        else:
            if best_cam == pending_camera:
                pending_camera_steps += 1
            else:
                pending_camera = best_cam
                pending_camera_steps = 1

            current_duration = current_time - segment_start
            if (
                pending_camera_steps >= SPEAKER_SWITCH_CONFIRMATION_STEPS
                and current_duration >= MIN_SHOT_DURATION_SEC
                and not is_near_boundary
            ):
                close_segment(current_time)
                current_camera = best_cam
                segment_start = current_time
                pending_camera = None
                pending_camera_steps = 0
                confidence_totals[current_camera] = 0.0
                confidence_counts[current_camera] = 0

        if current_camera is not None:
            confidence_totals[current_camera] = (
                confidence_totals.get(current_camera, 0.0)
                + camera_confidences.get(current_camera, 0.0)
            )
            confidence_counts[current_camera] = confidence_counts.get(current_camera, 0) + 1

        current_time += 0.5

    if current_camera and segment_start < end_time:
        close_segment(end_time)

    logger.info(f"Generated {len(segments)} camera switches.")
    return segments


def export_roughcut_fcpxml(segments: List[dict], output_path: str, fps: float = 25.0):
    """Generates a basic FCPXML 1.8 file from the AI segments."""
    import xml.etree.ElementTree as ET

    total_duration = segments[-1]["end"] if segments else 0.0

    fcpxml = ET.Element("fcpxml", version="1.8")
    resources = ET.SubElement(fcpxml, "resources")

    format_id = "r1"
    ET.SubElement(resources, "format", id=format_id, name="FFVideoFormat1080p25",
                  frameDuration=f"1/{int(fps)}s", width="1920", height="1080")

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name="SyncCut AI Rough Cut")
    project = ET.SubElement(event, "project", name="AI Multicam Assembly")

    sequence = ET.SubElement(project, "sequence", format=format_id,
                             duration=f"{int(total_duration * fps)}/{int(fps)}s")
    spine = ET.SubElement(sequence, "spine")

    for i, seg in enumerate(segments):
        start_frames = int(seg["start"] * fps)
        end_frames = int(seg["end"] * fps)
        duration_frames = end_frames - start_frames

        clip = ET.SubElement(spine, "clip", name=f"{seg['camera']} - Cut {i + 1}",
                             offset=f"{start_frames}/{int(fps)}s",
                             duration=f"{duration_frames}/{int(fps)}s")
        ET.SubElement(clip, "marker", start="0s", duration="1/25s", value="AI SyncCut Switch")

    tree = ET.ElementTree(fcpxml)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)