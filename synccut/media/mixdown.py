"""
mixdown.py — Build a single "master" WAV from N camera audio stems, each shifted
onto the reference timeline so the whole session collapses to one aligned audio bed.

This powers the WaveSurfer timeline in the studio UI (Deliverable 2): the browser
streams this real mixed-down WAV instead of a placeholder.
"""
import os
import wave

import numpy as np
from scipy.io import wavfile


def build_master_mixdown(wav_paths, offsets, out_path, target_sr=None):
    """
    Sum N audio stems onto a common timeline.

    Args:
        wav_paths: iterable of extracted mono WAV paths (index 0 = reference).
        offsets:   per-stem delay in seconds relative to the reference.
        out_path:  destination .wav path.
        target_sr: sample rate to write; defaults to the first readable stem's rate.

    Returns:
        The output path on success, or ``None`` if nothing could be mixed.
    """
    signals = []
    sr = int(target_sr or 16000)
    for path in wav_paths:
        if path.lower().endswith(".s16le"):
            sig = np.memmap(path, dtype=np.int16, mode="r")
        else:
            stem_sr, sig = wavfile.read(path, mmap=True)
            if stem_sr != sr or sig.ndim != 1 or sig.dtype != np.int16:
                raise ValueError(f"Expected mono {sr} Hz PCM16 audio in {path}")
        signals.append(sig)
    if not signals:
        return None

    offs = [float(offsets[i]) if i < len(offsets) else 0.0 for i in range(len(signals))]
    min_off = min([0.0, *offs])
    starts = [(o - min_off) * sr for o in offs]
    total = max(int(round(start)) + len(sig) for start, sig in zip(starts, signals))
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    chunk_samples = sr * 10
    with wave.open(out_path, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sr)
        for out_start in range(0, total, chunk_samples):
            out_end = min(total, out_start + chunk_samples)
            timeline = np.arange(out_start, out_end, dtype=np.float64)
            mixed = np.zeros(out_end - out_start, dtype=np.float32)
            for samples, start in zip(signals, starts):
                source_positions = timeline - start
                valid = (source_positions >= 0) & (source_positions < len(samples) - 1)
                if not np.any(valid):
                    continue
                positions = source_positions[valid]
                lower = positions.astype(np.int64)
                fraction = (positions - lower).astype(np.float32)
                left = np.asarray(samples[lower], dtype=np.float32) / 32768.0
                right = np.asarray(samples[lower + 1], dtype=np.float32) / 32768.0
                mixed[valid] += left + (right - left) * fraction
            mixed /= max(1, len(signals))
            pcm = (np.clip(mixed, -1.0, 1.0) * 32767.0).astype(np.int16)
            writer.writeframesraw(pcm.tobytes())
    return out_path
