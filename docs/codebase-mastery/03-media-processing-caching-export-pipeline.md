# Order 3 — Media Processing, Caching, and the Export Pipeline

**Read this after** [02-backend-architecture-and-orchestration.md](./02-backend-architecture-and-orchestration.md).
**Read this before** [04-frontend-studio-experience-and-timeline-editing.md](./04-frontend-studio-experience-and-timeline-editing.md).

Doc 01 explained the *math* of synchronization. Doc 02 explained *how a job runs*.
This document explains the layer in between: **how a real camera file becomes (a) a clean
audio array the math can eat, (b) a lightweight proxy the browser can scrub, and
(c) a timeline file that Premiere, Resolve, or Final Cut can actually open.**

We teach it in the order the bytes actually move.

Relevant files (read alongside this doc):

- [../../synccut/media/extract.py](../../synccut/media/extract.py) — decode any file → mono 16 kHz WAV
- [../../synccut/media/proxy_gen.py](../../synccut/media/proxy_gen.py) — 720p H.264 proxies for the browser
- [../../synccut/media/mixdown.py](../../synccut/media/mixdown.py) — sum N aligned stems → one master WAV
- [../../synccut/export/timeline_builder.py](../../synccut/export/timeline_builder.py) — sync report → OpenTimelineIO → FCPXML/EDL/AAF
- [../../synccut/export/fcp7_exporter.py](../../synccut/export/fcp7_exporter.py) — hand-written FCP7 XML (xmeml v4) for Premiere
- [../../synccut/export/switch_timeline.py](../../synccut/export/switch_timeline.py) — AI segments → single-track rough cut
- [../../synccut/api/routes.py](../../synccut/api/routes.py) — the `/api/export/timeline` dispatcher
- [../../synccut/workers/tasks.py](../../synccut/workers/tasks.py) — calls all of the above in order
- [../../synccut/paths.py](../../synccut/paths.py) — where every artifact lands

---

## 0. The one-sentence version

Raw camera files are **not** usable by any of the three consumers (the DSP math, the
browser, the NLE), so this layer **normalizes** each file into the exact shape each
consumer needs — a mono 16 kHz WAV for the math, a 720p MP4 for the browser, and a
timecoded XML/EDL for the editor — caching everything so re-runs are cheap.

There are **five transforms** in this layer:

| # | Transform | Input | Output | Consumer | File |
|---|---|---|---|---|---|
| 1 | **Decode audio** | any video/audio | mono 16 kHz PCM WAV | sync math | `media/extract.py` |
| 2 | **Generate proxy** | 4K/1080p video | 720p H.264 MP4 | browser `<video>` | `media/proxy_gen.py` |
| 3 | **Mix down master** | N aligned WAVs | one mixed WAV | browser waveform | `media/mixdown.py` |
| 4 | **Serve previews** | session media | waveform bytes, JPEG thumb, media stream | browser timeline | `api/routes.py` |
| 5 | **Export timeline** | sync report + project | FCPXML / xmeml / EDL / AAF / PDF | Premiere, Resolve, FCP | `export/*` |

Now let's walk each one.

---

## 1. Transform 1 — decoding: every file becomes one identical format

### 1.1 Why normalization is mandatory

Look at the inputs the app accepts. The frontend accepts this list
([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx)):

```
video/*,audio/*,.mp4,.mov,.m4v,.mkv,.avi,.webm,.mts,.m2ts,.ts,.mpg,.mpeg,
.3gp,.wmv,.mp3,.wav,.m4a,.aac,.flac,.ogg
```

That is video containers, audio containers, phone formats, broadcast formats, and codecs
from AAC to ProRes. Meanwhile the sync math (doc 01) assumes **one** representation: an
array of signed 16-bit integers at a known sample rate.

You cannot cross-correlate a `.mov` against an `.mp3` directly — you need a common
denominator first. That common denominator is defined by one constant:

```python
TARGET_SR = 16000  # 16kHz mono is plenty for timing correlation
```
— [extract.py](../../synccut/media/extract.py#L10)

### 1.2 The decode command, decoded

The whole normalization is one FFmpeg invocation
([extract.py](../../synccut/media/extract.py#L29-L37)):

```python
cmd = [
    get_ffmpeg_path(), "-y", "-i", input_path,
    "-vn",                 # no video
    "-ac", "1",            # mono
    "-ar", str(TARGET_SR), # 16kHz
    "-c:a", "pcm_s16le",   # uncompressed signed 16-bit little-endian
    "-loglevel", "error",
    out_path
]
```

Read it flag by flag — each one is a deliberate decision:

- **`-vn`** — throw the video away. The math only cares about sound, and decoding video
  would waste minutes per file.
- **`-ac 1`** — downmix to one channel. Doc 01 relies on a *single* waveform per camera;
  multi-channel would mean picking a channel or correlating all of them.
- **`-ar 16000`** — resample to 16 kHz. Timing resolution is then 62.5 µs/sample — far
  finer than the millisecond offsets we care about — while keeping the FFT small.
- **`-c:a pcm_s16le`** — write *uncompressed* PCM. This matters: the output is a matrix
  of `int16`, which is exactly what `np.memmap(..., dtype=np.int16)` expects downstream.
- **`-y`** — overwrite, because we own the output path and it is always inside our cache.

The result is a `.wav` that is 44-byte header + raw int16 samples. This is why the cache
check later tests `> 44` bytes — the header alone is 44 bytes, so anything larger means
there is real audio behind it.

### 1.3 The cache: the single biggest performance decision

Re-running a full sync on the same session would otherwise re-decode every file. The
guard at the top of `extract_audio` prevents that
([extract.py](../../synccut/media/extract.py#L22-L27)):

```python
if os.path.exists(out_path) and os.path.getsize(out_path) > 44:
    try:
        if os.path.getmtime(out_path) >= os.path.getmtime(input_path):
            return out_path
    except OSError:
        pass
```

Three things to notice, because each is a real lesson:

1. **The cache key is the filename**, not a hash (`f"{base}.wav"`). So two different
   files with the same basename in one session would collide. In practice upload naming
   avoids this, but it is a sharp edge worth knowing.
2. **Freshness is by mtime**, not a content hash. If you edit a source file but keep an
   older mtime (rare), the stale WAV is reused. Cheap and "good enough".
3. **`> 44` guard** is a validity check, not just an existence check — a truncated or
   zero-byte file is treated as absent.

The `OSError` swallow handles the case where the file vanished between the `exists()`
call and the `getmtime()` call — a trivial race, handled without a crash.

### 1.4 Batch decode: parallel by default

Multi-camera jobs decode every file concurrently
([extract.py](../../synccut/media/extract.py#L49-L65)):

```python
max_workers = min(len(input_paths), max(2, detected_cpus))
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    return list(executor.map(lambda p: extract_audio(p, output_dir=output_dir), input_paths))
```

**Why threads and not processes?** FFmpeg runs as a *separate OS process* spawned by
`subprocess.run`. The Python thread only waits on that subprocess, so the GIL is released
and the real work happens in parallel anyway. Threads are the right tool here; processes
would add pickling overhead for no gain.

### 1.5 Probing: reading metadata without decoding the whole file

Two helpers ask `ffprobe` for just the numbers we need:

```python
def get_duration(input_path):                     # total length, seconds
def get_video_frame_rate(input_path):             # avg_frame_rate, e.g. "30000/1001"
```
— [extract.py](../../synccut/media/extract.py#L68-L95)

`get_video_frame_rate` is worth reading closely because it handles the ugly NTSC cases:

```python
numerator, separator, denominator = value.partition("/")
rate = float(numerator) / float(denominator) if separator else float(value)
return rate if rate > 0 else None
```

FFprobe returns `"30000/1001"` (≈29.97), not `29.97`. The code splits on `/` and divides,
and returns `None` for the `"0/0"` sentinel that FFprobe emits for streams it cannot
measure. That `None` is meaningful downstream — `run_sync_task` uses it to decide whether
it can compute `offset_frames` at all:

```python
"offset_frames": (offset * frame_rate if frame_rate is not None
                  else camera.get("offset_frames")),
```
— [tasks.py](../../synccut/workers/tasks.py#L204-L207)

**Dependency note:** both helpers call `get_ffmpeg_path()` / `get_ffprobe_path()`, which
resolve the binary from the PyInstaller bundle first, then fall back to `PATH`
(doc 02, §paths). This is what lets the packaged MSIX app ship a private FFmpeg.

---

## 2. Transform 2 — proxies: making 4K footage scrubbable in a browser

### 2.1 The problem

An editor's source files are often 4K/50fps ProRes or HEVC — hundreds of MB per minute.
A `<video>` element trying to seek through that in a WebView is a slideshow. So the app
generates **proxies**.

The docstring states the intent plainly
([proxy_gen.py](../../synccut/media/proxy_gen.py#L8-L14)):

```
WHY: Editors cannot scrub raw 4K footage in a browser. We generate
a lightweight file for the web UI, while keeping the original for export.
```

### 2.2 The proxy command

```python
command = [
    ffmpeg_bin, "-y", "-i", input_path,
    "-vf", "scale=-2:720",     # height 720, width auto (keeps aspect, even number)
    "-c:v", "libx264",
    "-preset", "veryfast",     # trade size for speed
    "-crf", "28",              # aggressive compression — it's a proxy
    "-c:a", "aac", "-b:a", "128k",
    output_path,
]
```
— [proxy_gen.py](../../synccut/media/proxy_gen.py#L27-L38)

Two details worth internalizing:

- **`scale=-2:720`** — the `-2` (not `-1`) forces the width to a multiple of 2, which
  H.264 requires. Using `-1` can produce odd widths and a hard encoder error.
- **`-crf 28`** — CRF is a quality dial where higher = smaller. 28 is deliberately
  low quality: the proxy is for *scrubbing*, never for final output. The original file is
  kept untouched and used at export time (see §5).

Note the docstring claims the proxy has a **burned-in timecode** ("drawtext"), but the
actual filter chain is only `scale=-2:720` — there is no `drawtext` filter. **Doc note:
the comment is stale; trust the command, not the comment.**

### 2.3 Non-fatal by design

Notice where proxy generation is called
([tasks.py](../../synccut/workers/tasks.py#L99-L111)):

```python
try:
    proxy_path = generate_proxy(path, proxy_dir)
    results.append({"original": path, "proxy": proxy_path})
except Exception as e:
    logger.warning(f"Proxy generation failed for {path}: {e}")
    results.append({"original": path, "proxy": path})   # fall back to the original
```

If the proxy fails, the **original path is used instead**. Proxies are a performance
optimization, not a correctness requirement — a job must never fail because a preview
could not be built. This "visual-only, never fatal" pattern recurs in this document.

---

## 3. Transform 3 — the master mixdown: N stems → one aligned bed

### 3.1 What it is for

After sync we know each camera's `offset_s` (doc 01). The browser needs **one** waveform
to draw under the timeline. So `build_master_mixdown` sums all the aligned audio stems
onto a single timeline
([mixdown.py](../../synccut/media/mixdown.py#L15-L27)):

> Sum N audio stems onto a common timeline.

### 3.2 The alignment math (the interesting part)

```python
min_off = min([0.0, *offs])
starts = [(o - min_off) * sr for o in offs]
total = max(int(round(start)) + len(sig) for start, sig in zip(starts, signals))
```
— [mixdown.py](../../synccut/media/mixdown.py#L41-L44)

In words:

1. Find the earliest start across all stems (`min_off`, which is clamped to include `0.0`
   so the reference never starts negative).
2. Re-base every offset so the earliest becomes `0` — this keeps the output timeline
   non-negative.
3. Convert seconds → samples by multiplying by `sr` (16000).
4. The total output length is the furthest `start + len(stem)`.

### 3.3 The mixing loop, including fractional resampling

```python
for out_start in range(0, total, chunk_samples):
    ...
    for samples, start in zip(signals, starts):
        source_positions = timeline - start
        valid = (source_positions >= 0) & (source_positions < len(samples) - 1)
        positions = source_positions[valid]
        lower = positions.astype(np.int64)
        fraction = (positions - lower).astype(np.float32)
        left = np.asarray(samples[lower], dtype=np.float32) / 32768.0
        right = np.asarray(samples[lower + 1], dtype=np.float32) / 32768.0
        mixed[valid] += left + (right - left) * fraction
    mixed /= max(1, len(signals))
```
— [mixdown.py](../../synccut/media/mixdown.py#L54-L69)

This is a **linear interpolation resampler**. Because a stem's start is `offset * 16000`
and usually not an integer, each output sample maps to a *fractional* read position in
the source. The code reads the two neighbouring int16 samples, normalizes to `[-1, 1]`
(divide by 32768), and linearly interpolates between them. It then sums all stems and
divides by the stem count so the mix cannot clip.

**Why chunked?** `chunk_samples = sr * 10` (10 seconds at a time). Long recordings
(multi-hour weddings) cannot be held as one `float32` array in memory; processing 10 s
windows keeps RAM flat. The writer only ever holds one chunk.

### 3.4 Why this is deliberately non-fatal

In `run_sync_task` the mixdown is wrapped so a failure cannot kill the sync
([tasks.py](../../synccut/workers/tasks.py#L243-L256)):

```python
# Deliverable 2: collapse N stems into one aligned master WAV for the
# browser waveform. Visual-only, so a failure here must not kill the sync.
master_audio_url = None
try:
    mix_path = build_master_mixdown(...)
    if mix_path:
        master_audio_url = _master_audio_url(session_id)
except Exception:
    logger.warning("Master mixdown failed", exc_info=True)
```

Same principle as proxies: the waveform is cosmetic, the sync result is the product.

---

## 4. Transform 4 — serving previews to the browser

The frontend never touches the filesystem; it fetches everything through the API. Four
routes make the Studio feel like a real editor (all under `/api/session/<session_id>/`):

| Route | Returns | Used by |
|---|---|---|
| `master_audio` | the mixed WAV (range requests) | WaveSurfer master waveform |
| `waveform/<index>` | precomputed waveform bytes | per-camera lane peaks |
| `media/<index>` | the original/proxy video stream | `<video>` elements |
| `thumbnail/<index>?time=` | a JPEG at a timecode | timeline filmstrip |

Two implementation notes that matter:

- **Waveform files are precomputed, not computed on request.** `run_sync_task` records
  `waveform_files` in the report and assigns `waveform_index` per camera
  ([tasks.py](../../synccut/workers/tasks.py#L224-L226)). At 100 Hz
  (`SYNC_WAVEFORM_RATE = 100` in [config.py](../../synccut/config.py#L27)) these are tiny.
- **`media/<index>` accepts a `?token=` query parameter**, because an `<img>`/`<video>`
  cannot send an `Authorization` header. The frontend builds that URL itself
  ([api.ts](../../synccut-studio/src/lib/api.ts#L111-L115)):

  ```ts
  export function getSessionMediaUrl(sessionId: string, index: number) {
    const token = localStorage.getItem('synccut_auth_token');
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
    return `${API_BASE}/api/session/${encodeURIComponent(sessionId)}/media/${index}${tokenParam}`;
  }
  ```

  This is exactly the "Bearer / query-token / cookie" auth resolution order described in
  doc 02.

**Known defect (important for following the code):**
[`/api/health`] is fine, but `/api/system/storage`
([routes.py](../../synccut/api/routes.py#L1283-L1286)):

```python
@bp.route("/api/system/storage", methods=["GET"])
def api_system_storage():
    from synccut.paths import get_storage_info
    return jsonify(get_storage_info())
```

…imports `get_storage_info`, which **does not exist** in
[paths.py](../../synccut/paths.py). So this route raises `ImportError` → the global error
handler returns a 500. The frontend has a matching client function
(`getStorageInfoApi`) that would break if called. This is documented in doc 06 as
technical debt; there is no `get_storage_info` implementation anywhere in the repo.

---

## 5. Transform 5 — export: turning the result into an editable timeline

This is the most code-dense part of the app, so take it slowly.

### 5.1 The core idea

After sync, every camera has an offset. On a timeline "where t = 0 is the earliest
camera starting", each camera sits at `offset_s - min(offset_s)`. Export means: build a
timeline object that places each source clip at that position, plus an optional
**PROGRAM** track of edit decisions — then serialize it.

The unit of work is **OpenTimelineIO (OTIO)** — a vendor-neutral timeline model — with
two custom serializers bolted on for the formats OTIO handles poorly.

### 5.2 `build_timeline` — report → OTIO

The signature
([timeline_builder.py](../../synccut/export/timeline_builder.py#L16)):

```python
def build_timeline(report_path, media_dir, fps=25.0, name="synccut_timeline", project=None):
```

It first **reconciles two possible report shapes** (a legacy plain list vs. the modern
dict with `cameras`/`results`) and then folds in the React project's camera edits:

```python
results = [{**row,
    "offset_s": cameras.get(row.get("source"), {}).get("offset_s", ...),
    "drift_ppm": cameras.get(row.get("source"), {}).get("drift_ppm", ...)}
    for row in results]
```
— [timeline_builder.py](../../synccut/export/timeline_builder.py#L26-L37)

**Design principle to notice:** the export layer is a *merge* of three sources of truth —
the sync report, the saved `project.json`, and (via the route) the live React timeline.
Later sources win. This is why the export "stays in lock-step" with what the user sees.

The timeline origin is then the earliest offset:

```python
timeline_origin = min(r["offset_s"] for r in valid)
...
timeline_start_sec = max(0.0, r["offset_s"] - timeline_origin)
```
— [timeline_builder.py](../../synccut/export/timeline_builder.py#L71, #L99)

Each camera becomes a **video track** with a **Gap** (leading silence) followed by the
clip, and — critically — the offset is stamped into metadata so downstream tools keep it:

```python
clip.metadata["synccut"] = {
    "offset_s": r["offset_s"], "drift_ppm": r.get("drift_ppm", 0.0),
    "state": r.get("state", "VERIFY"), "psr": r.get("psr"),
}
```
— [timeline_builder.py](../../synccut/export/timeline_builder.py#L124-L129)

### 5.3 The PROGRAM track — the actual edited cut

If the project has a `program` (the list of camera segments the user/AI decided), the
builder lays them out **sequentially on one track**, inserting gaps and reading each clip
**from its own source file at the right in-point**:

```python
start = max(float(segment.get("start", 0)), float(row["offset_s"]))
end = min(float(segment.get("end", start)), float(row["offset_s"]) + source_duration)
...
source_range=otio.opentime.TimeRange(
    start_time=otio.opentime.RationalTime(round((start - row["offset_s"]) * fps), fps),
    duration=otio.opentime.RationalTime(round((end - start) * fps), fps),
)
```
— [timeline_builder.py](../../synccut/export/timeline_builder.py#L163-L184)

Read the `start_time` line carefully — this is the crux of a multicam export. A segment
on the *program* timeline from `start` to `end` corresponds to a range in that camera's
*own file* from `(start - offset_s)` to `(end - offset_s)`. Get this subtraction wrong
and every clip is offset by its camera's sync delay. The clamping to
`[offset_s, offset_s + duration]` guarantees we never request frames the file does not have.

### 5.4 `export_timeline` — serializer + format-specific patches

```python
def export_timeline(timeline, output_path):
    if output_path.lower().endswith(".edl"):
        ...  # hand-written CMX 3600 (OTIO has no EDL adapter)
    otio.adapters.write_to_file(timeline, output_path)
    if output_path.lower().endswith(".fcpxml"):
        _fix_asset_audio_attributes(output_path)
        _add_audio_components(output_path)
        _wrap_with_library_event(output_path)
```
— [timeline_builder.py](../../synccut/export/timeline_builder.py#L230-L260)

Three things are happening:

1. **EDL is hand-written** because OTIO ships no EDL adapter. The code emits CMX 3600
   with real `HH:MM:SS:FF` timecode (note: `int((start_sec%1)*25)` assumes 25 fps —
   a hardcoded assumption, see doc 06):

   ```python
   start_tc = f"00:00:{int(start_sec)//60:02d}:{int(start_sec)%60:02d}:{int((start_sec%1)*25):02d}"
   ```
   — [timeline_builder.py](../../synccut/export/timeline_builder.py#L244)

2. **FCPXML gets three post-processing patches** because OTIO's FCPXML output does not
   satisfy Resolve:
   - `_fix_asset_audio_attributes` — probes each media file with ffprobe and corrects
     `hasAudio` / `audioChannels` / `audioRate` on the `<asset>` tags. If a file has no
     audio, those attributes are *removed*. (Windows paths also get their leading slash
     stripped: `if re.match(r"^/[A-Za-z]:", file_path): file_path = file_path[1:]`.)
   - `_add_audio_components` — for each `<video>` element, injects a sibling `<audio>`
     with the right `audioChannelSource`, so Resolve actually links the audio.
   - `_wrap_with_library_event` — wraps the `<project>` in `<library><event>` because
     Resolve refuses a bare project.

   These are pure string/regex transformations on the XML. They are the kind of
   "compatibility shim" that exists because file-format *specs* and file-format
   *implementations* disagree.

### 5.5 `fcp7_exporter.py` — the Premiere path

Premiere does not read FCPXML; it reads the older **FCP7 XML (`xmeml` v4)**. This file
builds that document by hand with `xml.etree.ElementTree`.

The most important function is the frame-rate mapper
([fcp7_exporter.py](../../synccut/export/fcp7_exporter.py#L18-L40)):

```python
if abs(fps_val - 23.976) < 0.05 or abs(fps_val - (24000/1001)) < 0.01:
    return 24, "TRUE", False
elif abs(fps_val - 29.97) < 0.05 or abs(fps_val - (30000/1001)) < 0.01:
    return 30, "TRUE", False
elif abs(fps_val - 59.94) < 0.05 or abs(fps_val - (60000/1001)) < 0.01:
    return 60, "TRUE", False
else:
    return int(round(fps_val)), "FALSE", False
```

This encodes real NLE trivia: NTSC rates are *integer timebases* (24/30/60) with an
`ntsc=TRUE` flag, not the fractional number. Get this wrong and Premiere throws the
classic "frame rate mismatch" dialog.

The placement logic uses a different convention from `timeline_builder` — instead of
placing clips at their offset, it **trims the head** so all clips start at frame 0:

```python
max_offset = max(r["offset_s"] for r in valid)
trim_in_sec = max(0.0, max_offset - r["offset_s"])
```
— [fcp7_exporter.py](../../synccut/export/fcp7_exporter.py#L93, #L119)

So `clip_in` (the source in-point) absorbs the lead, and every clip lands at
`timeline_start = 0`. Both approaches are valid; they are simply two different NLE
conventions. The docstring states the rounding rule explicitly (round half-up everywhere)
to guarantee video and audio frame boundaries agree.

The structure it emits:

- one **video track per camera** (`clipitem-video-N`), each with a `<file>` reference,
- one **audio track per source**, reference first, then cameras (A1 = reference),
- a top-level `<timecode>` and `<rate>` block,
- `offset_s` and `drift_ppm` recorded in `<logginginfo><description>` for auditability:

  ```python
  ET.SubElement(logging_info, "description").text = (
      f"SyncCut offset_s={cam['offset_s']:.9f}; drift_ppm={cam['drift_ppm']:.6f}")
  ```
  — [fcp7_exporter.py](../../synccut/export/fcp7_exporter.py#L232-L235)

### 5.6 `switch_timeline.py` — the AI rough cut as a real timeline

`switches.json` is a list of `{camera, start, end}` segments from the AI active-speaker
pass. `build_switch_timeline` turns it into a single video track where each segment is
cut from that camera's own file
([switch_timeline.py](../../synccut/export/switch_timeline.py#L21-L67)):

```python
timeline = otio.schema.Timeline(name=name)
track = otio.schema.Track(name="Rough Cut", kind=otio.schema.TrackKind.Video)
for seg in segments:
    file_path = os.path.join(media_dir, seg["file"])
    ...
    source_range=otio.opentime.TimeRange(
        start_time=otio.opentime.RationalTime(round(start_sec * fps), fps),
        duration=otio.opentime.RationalTime(round(clip_duration * fps), fps),
    )
```

The module docstring is worth reading — it explains *why this file exists*
([switch_timeline.py](../../synccut/export/switch_timeline.py#L1-L13)): it **replaced** an
older `export_switch_edl.py` that emitted raw seconds instead of `HH:MM:SS:FF` and no CMX
fields, so it would not import. The fix was to build a proper OTIO timeline and reuse the
already-verified `export_timeline` (with all three FCPXML patches). **Lesson: reuse the
export path that already works rather than writing a second, subtly-broken one.**

There is *also* a separate, simpler FCPXML writer inside the AI module itself —
`export_roughcut_fcpxml` in [rough_cut.py](../../synccut/ai/rough_cut.py#L295-L327) —
which hand-writes a minimal FCPXML 1.8 with one `<clip>` per segment. So there are
**two** ways AI segments reach FCPXML (see §6).

### 5.7 The dispatcher — `/api/export/timeline`

Everything above is wired together in one route
([routes.py](../../synccut/api/routes.py#L754-L913)). Read its order of operations — it
is the complete export contract:

1. **Validate** — `session_id` required; and either `sync_report.json` exists **or** the
   React timeline was sent (`if not os.path.exists(report_path) and not timeline_clips: 400`).
2. **Load** `project.json` if present, else a default skeleton.
3. **Override** the program with the **live React timeline** if `timeline_clips` was sent:

   ```python
   project["program"] = [{"camera": clip.get("name"),
       "start": float(clip.get("start", 0)),
       "end": float(clip.get("start", 0)) + float(clip.get("duration", 0)),
       "reason": clip.get("reason", "manual_nle_edit")} for clip in timeline_clips]
   ```
   — [routes.py](../../synccut/api/routes.py#L789-L798)
4. **Validate fps** (`1 <= fps <= 120`).
5. **Persist** the project atomically — write to `.tmp` then `os.replace`:

   ```python
   with open(project_path + ".tmp", "w", ...) as project_file:
       json.dump(project, project_file, allow_nan=False, separators=(",", ":"))
   os.replace(project_path + ".tmp", project_path)
   ```
   — [routes.py](../../synccut/api/routes.py#L809-L812)

   `allow_nan=False` and the atomic replace are deliberate: they guarantee a valid,
   never-half-written project file even if the process dies mid-write.
6. **Format dispatch**:

| `format` value | Output | Path |
|---|---|---|
| `fcp7` / `xmeml` / `xml` / `premiere` | `timeline_premiere.xml` | `export_fcp7_xml` |
| `aaf` | `synccut_multicam.aaf` | `build_timeline` → OTIO |
| `edl` | `synccut_timeline.edl` | `build_timeline` → hand EDL |
| `audit_pdf` / `pdf` | `sync_audit_report.pdf` | reportlab, inline in the route |
| *(default)* | `synccut_timeline.fcpxml` | `build_timeline` → FCPXML + patches |

7. **Errors** are caught and returned as `500 {error}` after `traceback.print_exc()`.

Notably, the **audit PDF is generated inline** in the route
([routes.py](../../synccut/api/routes.py#L855-L907)) with `reportlab`: a table of every
source's offset / drift / state, followed by the program edit list. It is the human-readable
"what did sync decide" artifact.

---

## 6. The full data flow, end to end

Here is the entire layer on one page, with the artifacts that appear on disk:

```
 uploaded file (mp4/mov/mkv/...)
        │
        │  [Transform 1]  extract_audio()
        │     ffmpeg -vn -ac 1 -ar 16000 -c:a pcm_s16le
        ▼
 sessions/<id>/_sync_audio/<base>.wav          ← cached; reused on re-run
        │                                        (also: _audio/ for legacy engine)
        │  [doc 01]  sync math → offsets, drift, confidence
        ▼
 sessions/<id>/sync_report.json                ← the authoritative result
        │
        ├── [Transform 3]  build_master_mixdown()   (non-fatal)
        │        ▼
        │   sessions/<id>/master_mix.wav          ← browser waveform source
        │
        ├── [Transform 2]  generate_proxy()          (non-fatal)
        │        ▼
        │   sessions/<id>/proxies/<base>_proxy.mp4 ← browser scrub source
        │
        ├── [AI]  generate_active_speaker_roughcut()
        │        ▼
        │   sessions/<id>/switches.json            ← AI segment list
        │
        └── [Transform 5]  export dispatch
                 ├─ timeline.fcpxml      (OTIO + 3 patches)
                 ├─ timeline_premiere.xml (xmeml v4)
                 ├─ timeline.edl          (CMX 3600, 25fps assumption)
                 ├─ synccut_multicam.aaf  (OTIO)
                 ├─ rough_cut.fcpxml      (AI segments)
                 └─ sync_audit_report.pdf (reportlab)
```

All under `%LOCALAPPDATA%\SyncCutStudio\sessions\<id>\` on Windows (doc 02, §paths).

---

## 7. Failure handling and the "fatal vs cosmetic" rule

A single principle runs through this whole layer, and it is the most useful thing to
carry away:

| Failure | Fatal? | Why |
|---|---|---|
| FFmpeg decode fails | **Yes** | Without audio there is no sync at all (`RuntimeError`) |
| Missing audio stream | No | `sync_core` synthesizes silence (doc 01) |
| Stale cache | No | mtime check re-extracts |
| Proxy generation fails | No | falls back to the original file |
| Master mixdown fails | No | sync result still valid |
| AI rough cut fails | No | falls back to reference angle / alternating sequence |
| One camera not found on export | No | warning + skip that track |
| Export format unsupported | No | defaults to FCPXML |

The rule: **anything that produces the product (the sync result) is fatal; anything that
merely makes it prettier or more editable is best-effort.** This is exactly what makes the
app survive real, messy media.

---

## 8. Self-check — can you answer these without re-reading?

1. Why does `extract_audio` use `-c:a pcm_s16le` instead of keeping the source codec?
2. The cache check tests `os.path.getsize(out_path) > 44`. Why 44?
3. Why does batch decode use a `ThreadPoolExecutor` and not a `ProcessPoolExecutor`?
4. In `build_master_mixdown`, why is there an interpolation between `lower` and `lower+1`?
5. In the PROGRAM track, why is the source `start_time` `(start - offset_s) * fps` and not
   just `start * fps`?
6. What are the three FCPXML patches, and what breaks in Resolve without each?
7. Why does `fcp7_exporter` trim the head to frame 0 instead of placing clips at their offset?
8. Name three operations in this layer that are explicitly allowed to fail silently.

If you can answer all eight, you understand this layer.
