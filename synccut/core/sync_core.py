"""Memory-bounded audio alignment for long multi-camera recordings."""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import numpy as np
from scipy import signal
from scipy.io import wavfile

from synccut.config import (
    MAX_TAU_SEC,
    SYNC_LOCKED_LOOP_ERROR_MS,
    SYNC_LOCKED_PSR,
    SYNC_LOCKED_WINDOW_STD_MS,
    SYNC_VERIFY_LOOP_ERROR_MS,
    SYNC_VERIFY_PSR,
    SYNC_VERIFY_WINDOW_STD_MS,
    SYNC_MASTER_TIE_MARGIN,
    SYNC_WAVEFORM_RATE,
    TARGET_SR,
)
from synccut.media.extract import get_duration
from synccut.paths import get_ffmpeg_path, get_ffprobe_path

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[Optional[float], Optional[float], str], None]


@dataclass
class _Audio:
    samples: np.ndarray
    path: str


def _cache_path(source_path: str, cache_dir: str) -> str:
    stat = os.stat(source_path)
    identity = f"{os.path.abspath(source_path)}\0{stat.st_size}\0{stat.st_mtime_ns}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, f"{digest}.s16le")


def _notify(callback: Optional[ProgressCallback], current, total, status: str) -> None:
    if callback:
        callback(current, total, status)


def _has_audio_stream(source_path: str) -> bool:
    command = [
        get_ffprobe_path(), "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_type", "-of", "csv=p=0", source_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Unable to inspect audio streams for {source_path}: {result.stderr.strip()}")
    return bool(result.stdout.strip())


def _create_silent_audio(path: str, duration_sec: float) -> np.memmap:
    sample_count = max(1, int(round(duration_sec * TARGET_SR)))
    output = np.memmap(path, dtype=np.int16, mode="w+", shape=(sample_count,))
    chunk_size = TARGET_SR * 60
    for start in range(0, sample_count, chunk_size):
        output[start:start + chunk_size] = 0
    output.flush()
    return output


def _decode_one(
    source_path: str,
    cache_dir: str,
    callback: Optional[ProgressCallback],
    cancel_check: Optional[Callable[[], None]],
    duration_sec: Optional[float],
) -> _Audio:
    os.makedirs(cache_dir, exist_ok=True)

    if source_path.lower().endswith(".wav"):
        sample_rate, samples = wavfile.read(source_path, mmap=True)
        if sample_rate == TARGET_SR and samples.dtype == np.int16 and samples.ndim == 1:
            _notify(
                callback,
                duration_sec,
                duration_sec,
                f"Using cached audio for {os.path.basename(source_path)}",
            )
            return _Audio(samples=samples, path=source_path)

    output_path = _cache_path(source_path, cache_dir)
    needs_decode = not os.path.exists(output_path) or os.path.getsize(output_path) == 0
    if needs_decode:
        partial_path = f"{output_path}.{os.getpid()}.{threading.get_ident()}.part"
        command = [
            get_ffmpeg_path(), "-nostdin", "-y", "-v", "error", "-i", source_path,
            "-vn", "-af", "highpass=f=80", "-ac", "1", "-ar", str(TARGET_SR), "-c:a", "pcm_s16le",
            "-f", "s16le", "-progress", "pipe:1", "-nostats", partial_path,
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            if process.stdout is None:
                raise RuntimeError(f"Unable to read FFmpeg progress for {source_path}")
            for line in process.stdout:
                if cancel_check:
                    cancel_check()
                key, separator, value = line.strip().partition("=")
                if separator and key == "out_time_us":
                    try:
                        decoded_sec = max(0.0, int(value) / 1_000_000.0)
                    except ValueError:
                        continue
                    _notify(
                        callback,
                        min(decoded_sec, duration_sec) if duration_sec else decoded_sec,
                        duration_sec,
                        f"Decoding audio: {os.path.basename(source_path)}",
                    )
            process.wait()
            stderr = process.stderr.read() if process.stderr else ""
            if process.returncode:
                if not _has_audio_stream(source_path):
                    if duration_sec is None or duration_sec <= 0:
                        duration_sec = get_duration(source_path)
                    _create_silent_audio(partial_path, duration_sec)
                    os.replace(partial_path, output_path)
                    _notify(
                        callback,
                        duration_sec,
                        duration_sec,
                        f"No audio stream in {os.path.basename(source_path)}; camera marked WEAK",
                    )
                    return _Audio(
                        samples=np.memmap(output_path, dtype=np.int16, mode="r"),
                        path=output_path,
                    )
                raise RuntimeError(f"FFmpeg failed on {source_path}: {stderr.strip()}")
            if not os.path.exists(partial_path) or os.path.getsize(partial_path) < 2:
                raise RuntimeError(f"FFmpeg produced no audio samples for {source_path}")
            os.replace(partial_path, output_path)
            _notify(
                callback,
                duration_sec,
                duration_sec,
                f"Decoded audio: {os.path.basename(source_path)}",
            )
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if os.path.exists(partial_path):
                os.remove(partial_path)
            raise

    if os.path.getsize(output_path) % np.dtype(np.int16).itemsize:
        raise RuntimeError(f"Cached PCM audio has an invalid byte length: {output_path}")
    if not os.path.exists(output_path):
        raise RuntimeError(f"Audio cache was not created for {source_path}")
    if not needs_decode and duration_sec is not None:
        _notify(
            callback,
            duration_sec,
            duration_sec,
            f"Using cached audio for {os.path.basename(source_path)}",
        )
    return _Audio(
        samples=np.memmap(output_path, dtype=np.int16, mode="r"),
        path=output_path,
    )


def _write_waveform_peaks(audio: _Audio, cache_dir: str, sample_rate: int) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    block_size = max(1, sample_rate // SYNC_WAVEFORM_RATE)
    source_size = os.path.getsize(audio.path) if os.path.exists(audio.path) else len(audio.samples)
    identity = f"{os.path.abspath(audio.path)}\0{len(audio.samples)}\0{source_size}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    output_path = os.path.join(cache_dir, f"{digest}.waveform")
    expected_size = (len(audio.samples) + block_size - 1) // block_size
    if os.path.exists(output_path) and os.path.getsize(output_path) == expected_size:
        return output_path

    partial_path = f"{output_path}.{os.getpid()}.{threading.get_ident()}.part"
    try:
        with open(partial_path, "wb") as target:
            for start in range(0, len(audio.samples), block_size * 60):
                samples = np.asarray(
                    audio.samples[start:start + block_size * 60], dtype=np.int32
                )
                usable = (len(samples) // block_size) * block_size
                if usable:
                    blocks = samples[:usable].reshape(-1, block_size)
                    peaks = np.max(np.abs(blocks), axis=1)
                    target.write(np.minimum(255, (peaks + 64) // 128).astype(np.uint8).tobytes())
            remainder = len(audio.samples) % block_size
            if remainder:
                tail = np.asarray(audio.samples[-remainder:], dtype=np.int32)
                peak = int(np.max(np.abs(tail)))
                target.write(bytes([min(255, (peak + 64) // 128)]))
        os.replace(partial_path, output_path)
    except BaseException:
        if os.path.exists(partial_path):
            os.remove(partial_path)
        raise
    return output_path


def _envelope(samples: np.ndarray, sample_rate: int, envelope_rate: int = 100) -> np.ndarray:
    block_size = max(1, sample_rate // envelope_rate)
    chunks = []
    for start in range(0, len(samples) - block_size + 1, block_size * 60):
        stop = min(len(samples), start + block_size * 60)
        usable = ((stop - start) // block_size) * block_size
        if usable == 0:
            continue
        block = np.asarray(samples[start:start + usable], dtype=np.float32).reshape(-1, block_size)
        chunks.append(np.sqrt(np.mean(block * block, axis=1)))
    if not chunks:
        raise ValueError("Audio source is shorter than one envelope block.")
    env = np.concatenate(chunks)
    env -= env.mean()
    std = float(env.std())
    if std > 0:
        env /= std
    return env


def _coarse_offset(reference: np.ndarray, camera: np.ndarray, sample_rate: int) -> float:
    envelope_rate = 100
    ref_env = _envelope(reference, sample_rate, envelope_rate)
    cam_env = _envelope(camera, sample_rate, envelope_rate)
    correlation = signal.correlate(ref_env, cam_env, mode="full", method="fft")
    lags = signal.correlation_lags(len(ref_env), len(cam_env), mode="full")
    max_lag = int(MAX_TAU_SEC * envelope_rate)
    valid = np.flatnonzero(np.abs(lags) <= max_lag)
    peak = int(valid[np.argmax(correlation[valid])])
    return float(lags[peak]) / envelope_rate


def _local_offsets(
    reference: np.ndarray,
    camera: np.ndarray,
    coarse_offset: float,
    sample_rate: int,
    cancel_check: Optional[Callable[[], None]],
    step_callback: Optional[Callable[[], None]],
) -> list[tuple[float, float, float, float]]:
    window_samples = min(8 * sample_rate, len(reference) // 2, len(camera) // 2)
    if window_samples < sample_rate:
        window_samples = min(len(reference), len(camera))
    margin_samples = min(2 * sample_rate, max(0, (len(camera) - window_samples) // 2))
    coarse_samples = coarse_offset * sample_rate
    min_ref_start = int(np.ceil(max(0.0, coarse_samples + margin_samples)))
    max_ref_start = int(np.floor(min(
        len(reference) - window_samples,
        coarse_samples + len(camera) - window_samples - margin_samples,
    )))
    if max_ref_start < min_ref_start:
        return []

    count = min(
        80,
        max(1, int((max_ref_start - min_ref_start) / (10.0 * sample_rate))),
    )
    if count == 1:
        ref_starts = [min_ref_start]
    else:
        ref_starts = np.linspace(
            min_ref_start,
            max_ref_start,
            count,
            dtype=np.int64,
        ).tolist()

    observations = []
    for ref_start in ref_starts:
        if cancel_check:
            cancel_check()
        expected_cam_start = int(round(ref_start - coarse_offset * sample_rate))
        cam_start = expected_cam_start - margin_samples
        cam_end = expected_cam_start + window_samples + margin_samples
        if cam_start < 0 or cam_end > len(camera):
            if step_callback:
                step_callback()
            continue

        ref_chunk = np.asarray(reference[ref_start:ref_start + window_samples], dtype=np.float32)
        cam_chunk = np.asarray(camera[cam_start:cam_end], dtype=np.float32)
        ref_chunk -= ref_chunk.mean()
        cam_chunk -= cam_chunk.mean()
        corr = signal.correlate(cam_chunk, ref_chunk, mode="valid", method="fft")
        peak = int(np.argmax(corr))
        fractional_peak = float(peak)
        if 0 < peak < len(corr) - 1:
            left, center, right = corr[peak - 1:peak + 2]
            denominator = float(left - 2.0 * center + right)
            if abs(denominator) > 1e-12:
                fractional_peak += float(0.5 * (left - right) / denominator)

        camera_match_start = cam_start + fractional_peak
        ref_time = ref_start / sample_rate
        camera_time = camera_match_start / sample_rate
        ref_energy = float(np.dot(ref_chunk, ref_chunk))
        cam_energy = float(np.dot(cam_chunk[int(fractional_peak):int(fractional_peak) + window_samples],
                                   cam_chunk[int(fractional_peak):int(fractional_peak) + window_samples]))
        confidence = float(np.clip(corr[peak] / np.sqrt(max(ref_energy * cam_energy, 1e-12)), 0.0, 1.0))
        sidelobes = np.abs(corr).copy()
        sidelobes[max(0, peak - 3):min(len(sidelobes), peak + 4)] = 0
        sidelobe_mean = float(sidelobes.mean())
        psr = float(abs(corr[peak]) / max(sidelobe_mean, 1e-12))
        observations.append((ref_time, ref_time - camera_time, confidence, psr))
        if step_callback:
            step_callback()
    return observations


def _window_count(reference, camera, coarse_offset: float, sample_rate: int) -> int:
    window_samples = min(8 * sample_rate, len(reference) // 2, len(camera) // 2)
    if window_samples < sample_rate:
        window_samples = min(len(reference), len(camera))
    margin_samples = min(2 * sample_rate, max(0, (len(camera) - window_samples) // 2))
    coarse_samples = coarse_offset * sample_rate
    min_ref_start = int(np.ceil(max(0.0, coarse_samples + margin_samples)))
    max_ref_start = int(np.floor(min(
        len(reference) - window_samples,
        coarse_samples + len(camera) - window_samples - margin_samples,
    )))
    if max_ref_start < min_ref_start:
        return 0
    return min(
        80,
        max(1, int((max_ref_start - min_ref_start) / (10.0 * sample_rate))),
    )


def _fit_offset(
    observations: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float, float]:
    if not observations:
        return 0.0, 0.0, 0.0, 0.0, float("inf")
    times = np.asarray([item[0] for item in observations], dtype=np.float64)
    offsets = np.asarray([item[1] for item in observations], dtype=np.float64)
    weights = np.asarray([max(item[2], 1e-3) for item in observations], dtype=np.float64)
    center = float(np.average(times, weights=weights))
    if len(observations) < 2 or np.ptp(times) == 0:
        slope = 0.0
        intercept = float(np.average(offsets, weights=weights))
    else:
        slope, centered_intercept = np.polyfit(
            times - center, offsets, 1, w=np.sqrt(weights)
        )
        intercept = float(centered_intercept - slope * center)
    confidence = float(np.average(weights))
    residuals = offsets - (intercept + slope * times)
    window_std_s = float(np.sqrt(np.average(residuals**2, weights=weights)))
    psr = float(np.median([item[3] for item in observations]))
    return intercept, float(slope), confidence, psr, window_std_s


def sync_arrays(
    arrays: Sequence[np.ndarray],
    names: Optional[Sequence[str]] = None,
    sample_rate: int = TARGET_SR,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> dict:
    """Align in-memory or memory-mapped mono arrays without whole-track FFTs."""
    if not arrays:
        raise ValueError("At least one audio source is required.")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive.")
    if names is None:
        names = ["Reference"] + [f"Camera {chr(65 + i)}" for i in range(len(arrays) - 1)]
    if len(names) != len(arrays):
        raise ValueError("names must contain one entry per audio source.")

    pair_coarse: dict[tuple[int, int], float] = {}
    pair_observations: dict[tuple[int, int], list[tuple[float, float, float, float]]] = {}
    for i in range(len(arrays)):
        for j in range(i + 1, len(arrays)):
            if cancel_check:
                cancel_check()
            if min(len(arrays[i]), len(arrays[j])) < sample_rate:
                continue
            if np.std(np.asarray(arrays[i][::max(1, sample_rate)], dtype=np.float32)) < 1e-5:
                continue
            if np.std(np.asarray(arrays[j][::max(1, sample_rate)], dtype=np.float32)) < 1e-5:
                continue
            pair_coarse[(i, j)] = _coarse_offset(arrays[i], arrays[j], sample_rate)

    total = len(pair_coarse) + sum(
        _window_count(arrays[i], arrays[j], offset, sample_rate)
        for (i, j), offset in pair_coarse.items()
    )
    total = max(1, total)
    completed = len(pair_coarse)
    _notify(progress_callback, completed, total, "Estimating long-term offset and drift")

    for (i, j), coarse in pair_coarse.items():
        if cancel_check:
            cancel_check()

        def _step() -> None:
            nonlocal completed
            completed += 1
            _notify(progress_callback, completed, total, "Estimating long-term offset and drift")

        observations = _local_offsets(
            arrays[i], arrays[j], coarse, sample_rate, cancel_check, _step
        )
        pair_observations[(i, j)] = observations

    # Solve all pair constraints together. The reference clock is fixed at zero.
    pair_metrics = {}
    for edge, observations in pair_observations.items():
        _, _, confidence, psr, window_std_s = _fit_offset(observations)
        pair_metrics[edge] = (confidence, psr, window_std_s)
    signal_strength = [
        float(np.std(np.asarray(samples[::max(1, sample_rate)], dtype=np.float32)))
        if len(samples) else 0.0
        for samples in arrays
    ]
    usable_indices = [index for index, strength in enumerate(signal_strength) if strength >= 1e-5]
    master_index = 0
    if usable_indices:
        master_scores = {
            index: float(np.mean([
                metrics[0]
                for edge, metrics in pair_metrics.items()
                if index in edge and metrics[0] > 0
            ])) if any(
                index in edge and metrics[0] > 0
                for edge, metrics in pair_metrics.items()
            ) else 0.0
            for index in usable_indices
        }
        best_score = max(master_scores.values())
        master_index = next(
            index for index in usable_indices
            if best_score - master_scores[index] <= SYNC_MASTER_TIE_MARGIN
        )
    unknown_indices = [index for index in range(len(arrays)) if index != master_index]
    unknown_position = {index: position for position, index in enumerate(unknown_indices)}
    unknown_count = len(unknown_indices)
    offsets = np.zeros(len(arrays), dtype=np.float64)
    slopes = np.zeros(len(arrays), dtype=np.float64)
    confidences = np.zeros(len(arrays), dtype=np.float64)
    confidences[master_index] = 1.0
    if unknown_count:
        equations = []
        offset_values = []
        slope_values = []
        equation_weights = []
        for edge, observations in pair_observations.items():
            intercept, slope, confidence, _, _ = _fit_offset(observations)
            if not observations:
                continue
            i, j = edge
            row = np.zeros(unknown_count, dtype=np.float64)
            if i != master_index:
                row[unknown_position[i]] = -1.0
            if j != master_index:
                row[unknown_position[j]] = 1.0
            equations.append(row)
            offset_values.append(intercept)
            slope_values.append(slope)
            equation_weights.append(max(confidence, 1e-3))
        if equations:
            matrix = np.asarray(equations)
            weights = np.sqrt(np.asarray(equation_weights))
            solved_offsets = np.linalg.lstsq(
                matrix * weights[:, None],
                np.asarray(offset_values) * weights,
                rcond=None,
            )[0]
            solved_slopes = np.linalg.lstsq(
                matrix * weights[:, None],
                np.asarray(slope_values) * weights,
                rcond=None,
            )[0]
            for index, position in unknown_position.items():
                offsets[index] = solved_offsets[position]
                slopes[index] = solved_slopes[position]

    camera_observations: dict[str, list[tuple[float, float, float, float]]] = {
        name: [] for name in names
    }
    for (i, j), observations in pair_observations.items():
        if i == master_index:
            camera_observations[names[j]].extend(observations)
        elif j == master_index:
            camera_observations[names[i]].extend(
                [(time, -offset, confidence, psr) for time, offset, confidence, psr in observations]
            )

    if completed < total:
        completed = total
        _notify(progress_callback, completed, total, "Audio alignment complete")

    loop_errors = []
    for (i, j), observations in pair_observations.items():
        if not observations:
            continue
        measured, _, confidence, _, _ = _fit_offset(observations)
        predicted = offsets[j] - offsets[i]
        loop_errors.append((measured - predicted, confidence))
    loop_error = (
        float(np.sqrt(np.average(
            np.square([error for error, _ in loop_errors]),
            weights=[max(weight, 1e-3) for _, weight in loop_errors],
        )))
        if loop_errors else 0.0
    )

    row_count = max((len(values) for values in camera_observations.values()), default=0)
    rows = []
    for row_index in range(row_count):
        camera_offsets = {}
        camera_confidence = {}
        row_times = []
        for camera_index in range(1, len(arrays)):
            camera_name = names[camera_index]
            observations = camera_observations[camera_name]
            if row_index >= len(observations):
                continue
            ref_time, measured_offset, confidence, _ = observations[row_index]
            camera_offsets[camera_name] = measured_offset
            camera_confidence[camera_name] = confidence
            row_times.append(ref_time)
        if not row_times:
            continue
        start = min(row_times)
        end = start + 8.0
        rows.append({
            "start": round(start, 6),
            "end": round(end, 6),
            "confidence": float(np.mean(list(camera_confidence.values()))) if camera_confidence else 0.0,
            "offset": float(np.mean(list(camera_offsets.values()))) if camera_offsets else 0.0,
            "offsets": camera_offsets,
            "cam_confidence": camera_confidence,
        })

    cameras = {}
    loop_error_ms = loop_error * 1000.0
    for i, name in enumerate(names):
        observations = camera_observations[name]
        incident_metrics = [
            pair_metrics[edge]
            for edge in pair_metrics
            if i in edge
        ]
        if not observations and incident_metrics:
            psr = float(np.average([metric[1] for metric in incident_metrics]))
            window_std_s = float(np.average([metric[2] for metric in incident_metrics]))
        elif observations:
            psr = float(np.median([item[3] for item in observations]))
            fitted = offsets[i] + slopes[i] * np.asarray(
                [item[0] for item in observations], dtype=np.float64
            )
            residuals = np.asarray([item[1] for item in observations]) - fitted
            window_std_s = float(np.std(residuals))
        else:
            psr = 0.0
            window_std_s = float("inf")
        if incident_metrics:
            confidences[i] = float(np.average([metric[0] for metric in incident_metrics]))
        window_std_ms = (
            window_std_s * 1000.0 if np.isfinite(window_std_s) else None
        )
        if i == master_index:
            state = "LOCKED"
        elif (
            window_std_ms is not None
            and
            psr >= SYNC_LOCKED_PSR
            and window_std_ms <= SYNC_LOCKED_WINDOW_STD_MS
            and loop_error_ms <= SYNC_LOCKED_LOOP_ERROR_MS
        ):
            state = "LOCKED"
        elif (
            window_std_ms is not None
            and
            psr >= SYNC_VERIFY_PSR
            and window_std_ms <= SYNC_VERIFY_WINDOW_STD_MS
            and loop_error_ms <= SYNC_VERIFY_LOOP_ERROR_MS
        ):
            state = "VERIFY"
        else:
            state = "WEAK"
        warnings = []
        if state == "WEAK" and i:
            warnings.append("Audio alignment could not be measured reliably.")
        drift_ppm = slopes[i] * 1_000_000.0
        if abs(drift_ppm) > 5:
            logger.warning("Measured clock drift for %s is %.2f ppm", name, drift_ppm)
        cameras[name] = {
            "offset_s": float(offsets[i]),
            "offset_ms": float(offsets[i] * 1000.0),
            "offset_samples": int(round(offsets[i] * sample_rate)),
            "offset_frames": float(offsets[i] * 25.0),
            "drift_ppm": float(drift_ppm),
            "drift_ms_per_hour": float(drift_ppm * 3.6),
            "link_confidence": float(confidences[i]),
            "psr": psr,
            "window_offsets": [float(item[1]) for item in observations],
            "window_std_ms": window_std_ms,
            "state": state,
            "warnings": warnings,
            "is_master": i == master_index,
            "duration_sec": len(arrays[i]) / sample_rate,
        }
    return {
        "cameras": cameras,
        "master_source": names[master_index],
        "loop_error_s": loop_error,
        "rows": rows,
    }


def sync_files(
    file_paths: Sequence[str],
    cache_dir: str,
    names: Optional[Sequence[str]] = None,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], None]] = None,
    max_workers: Optional[int] = None,
) -> dict:
    """Decode audio-only PCM files concurrently, then align their memmaps."""
    if not file_paths:
        raise ValueError("At least one media file is required.")
    if max_workers is None:
        max_workers = min(len(file_paths), max(2, os.cpu_count() or 1))

    durations = [get_duration(path) for path in file_paths]
    duration_total = sum(durations)
    if duration_total <= 0:
        raise ValueError("The input media has no measurable duration.")

    _notify(progress_callback, 0.0, 100.0, "Extracting audio from camera files")
    audio = [None] * len(file_paths)
    decoded_by_file = [0.0] * len(file_paths)
    progress_lock = threading.Lock()

    def decode_callback(index: int):
        def report(current, total, status):
            if current is None or total is None:
                _notify(progress_callback, None, None, status)
                return
            with progress_lock:
                decoded_by_file[index] = max(
                    decoded_by_file[index],
                    min(float(current), durations[index]),
                )
                decoded_duration = sum(decoded_by_file)
                _notify(
                    progress_callback,
                    min(70.0, 70.0 * decoded_duration / duration_total),
                    100.0,
                    status,
                )

        return report

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _decode_one,
                path,
                cache_dir,
                decode_callback(index),
                cancel_check,
                durations[index],
            ): index
            for index, path in enumerate(file_paths)
        }
        for future in as_completed(futures):
            if cancel_check:
                cancel_check()
            audio[futures[future]] = future.result()

    audio = [item for item in audio if item is not None]

    _notify(progress_callback, 70.0, 100.0, "Audio extraction complete; aligning cameras")

    def alignment_progress(current, total, status):
        if current is None or total is None or total <= 0:
            _notify(progress_callback, None, None, status)
            return
        percent = 70.0 + 25.0 * float(current) / float(total)
        _notify(progress_callback, min(95.0, percent), 100.0, status)

    result = sync_arrays(
        [item.samples for item in audio],
        names=names,
        sample_rate=TARGET_SR,
        progress_callback=alignment_progress,
        cancel_check=cancel_check,
    )
    result["audio_paths"] = [item.path for item in audio]
    result["waveform_paths"] = [
        _write_waveform_peaks(item, cache_dir, TARGET_SR) for item in audio
    ]
    return result
