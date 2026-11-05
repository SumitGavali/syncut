import os
import time

import numpy as np
import pytest

from synccut.core import sync_core
from synccut.core.sync_core import sync_arrays
from synccut.workers.job_control import JobCancelled


def _write_gated_noise(path, duration_s, sample_rate, seed):
    rng = np.random.default_rng(seed)
    sample_count = duration_s * sample_rate
    source = np.memmap(path, dtype=np.float32, mode="w+", shape=(sample_count,))
    source[:] = 0

    burst_samples = int(1.2 * sample_rate)
    for burst_start in range(0, sample_count, 2 * sample_rate):
        start = burst_start + sample_rate // 10
        end = min(start + burst_samples, sample_count)
        length = end - start
        noise = rng.standard_normal(length, dtype=np.float32)
        phase = np.linspace(0, 1, length, dtype=np.float32)
        noise *= 0.25 + 0.75 * np.abs(np.sin(phase * 2 * np.pi * 4))
        source[start:end] = noise
    source.flush()
    return source


def _make_recording(path, source, sample_rate, offset_s, drift_ppm, seed):
    rng = np.random.default_rng(seed)
    sample_count = len(source)
    output = np.memmap(path, dtype=np.float32, mode="w+", shape=(sample_count,))
    scale = 1 + drift_ppm * 1e-6
    chunk_size = 1_000_000

    for start in range(0, sample_count, chunk_size):
        end = min(start + chunk_size, sample_count)
        times = np.arange(start, end, dtype=np.float64) / sample_rate
        positions = (times + offset_s) * scale * sample_rate
        positions = np.clip(positions, 0, sample_count - 1)
        left = positions.astype(np.int64)
        right = np.minimum(left + 1, sample_count - 1)
        fraction = (positions - left).astype(np.float32)
        samples = source[left] * (1 - fraction) + source[right] * fraction
        samples += rng.normal(0, 0.015, size=end - start).astype(np.float32)
        output[start:end] = samples

    output.flush()
    return output


def test_sync_arrays_long_gated_audio_offsets_drift_and_progress(tmp_path):
    sample_rate = 16_000
    duration_s = 30 * 60
    source = _write_gated_noise(
        tmp_path / "source.f32", duration_s, sample_rate, seed=13
    )
    camera_a = _make_recording(
        tmp_path / "camera_a.f32", source, sample_rate, 3.217, 30, seed=21
    )
    camera_b = _make_recording(
        tmp_path / "camera_b.f32", source, sample_rate, -1.5, -12, seed=34
    )
    progress = []

    started = time.perf_counter()
    result = sync_arrays(
        [source, camera_a, camera_b],
        names=["Reference", "Camera A", "Camera B"],
        sample_rate=sample_rate,
        progress_callback=lambda current, total, status: progress.append(
            (current, total, status)
        ),
    )
    elapsed = time.perf_counter() - started

    assert abs(result["cameras"]["Camera A"]["offset_s"] - 3.217) < 0.002
    assert abs(result["cameras"]["Camera B"]["offset_s"] - (-1.5)) < 0.002
    assert abs(result["cameras"]["Camera A"]["drift_ppm"] - 30) < 1
    assert abs(result["cameras"]["Camera B"]["drift_ppm"] - (-12)) < 1
    assert elapsed < 30

    assert progress
    numeric = [(current, total) for current, total, _ in progress if total is not None]
    assert numeric
    currents = [current for current, _ in numeric]
    assert currents == sorted(currents)
    assert numeric[-1][0] == numeric[-1][1]


def test_sync_arrays_stops_promptly_when_cancelled():
    cancellation = JobCancelled("cancelled")
    started = time.perf_counter()

    def cancel():
        raise cancellation

    with pytest.raises(JobCancelled, match="cancelled"):
        sync_arrays(
            [np.zeros(16_000, dtype=np.float32)] * 2,
            cancel_check=cancel,
        )

    assert time.perf_counter() - started < 5


def test_silent_reference_is_weak_and_audible_camera_becomes_master():
    sample_rate = 16_000
    rng = np.random.default_rng(42)
    source = np.zeros(sample_rate * 20, dtype=np.float32)
    for burst in range(0, len(source), sample_rate * 2):
        source[burst:burst + sample_rate] = rng.standard_normal(sample_rate).astype(np.float32)
    camera = np.roll(source, -sample_rate // 3)
    result = sync_arrays(
        [np.zeros_like(source), source, camera],
        names=["Silent", "Camera A", "Camera B"],
        sample_rate=sample_rate,
    )

    assert result["master_source"] in {"Camera A", "Camera B"}
    assert result["cameras"]["Silent"]["state"] == "WEAK"
    assert result["cameras"][result["master_source"]]["is_master"] is True
    assert result["cameras"]["Camera B"]["offset_s"] - result["cameras"]["Camera A"]["offset_s"] == pytest.approx(
        1 / 3, abs=0.01
    )


def test_cleanest_audio_becomes_master_even_when_first_camera_is_audible(tmp_path):
    sample_rate = 16_000
    rng = np.random.default_rng(7)
    source = _write_gated_noise(
        tmp_path / "source.f32", 20, sample_rate, seed=13
    ).copy()
    noisy = source + rng.normal(0, 0.3, size=len(source)).astype(np.float32)

    result = sync_arrays(
        [noisy, source, source.copy()],
        names=["Noisy Reference", "Clean A", "Clean B"],
        sample_rate=sample_rate,
    )

    assert result["master_source"] in {"Clean A", "Clean B"}


def test_sync_files_reports_monotonic_overall_progress(monkeypatch, tmp_path):
    paths = [str(tmp_path / "camera_a.mp4"), str(tmp_path / "camera_b.mp4")]
    monkeypatch.setattr(sync_core, "get_duration", lambda path: 10.0)

    def fake_decode(path, cache_dir, callback, cancel_check, duration_sec):
        callback(2.0, duration_sec, f"Decoding {path}")
        callback(duration_sec, duration_sec, f"Decoded {path}")
        return sync_core._Audio(
            samples=np.arange(16_000, dtype=np.int16),
            path=path,
        )

    monkeypatch.setattr(sync_core, "_decode_one", fake_decode)
    progress = []

    result = sync_core.sync_files(
        paths,
        cache_dir=str(tmp_path / "audio-cache"),
        progress_callback=lambda current, total, status: progress.append(
            (current, total, status)
        ),
    )

    values = [current for current, total, _ in progress if total == 100.0]
    assert values == sorted(values)
    assert values[0] == 0.0
    assert values[-1] == pytest.approx(95.0)
    assert len(result["waveform_paths"]) == len(paths)
    assert all((tmp_path / "audio-cache" / os.path.basename(path)).stat().st_size == 100
               for path in result["waveform_paths"])
