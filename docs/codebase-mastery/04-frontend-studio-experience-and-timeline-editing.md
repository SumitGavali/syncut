# Order 4 — The Studio Frontend: Experience and Timeline Editing

**Read this after** [03-media-processing-caching-export-pipeline.md](./03-media-processing-caching-export-pipeline.md).
**Read this before** [05-data-model-and-persistence-layer.md](./05-data-model-and-persistence-layer.md).

Docs 01–03 taught the backend. This document teaches the **React app** in
`synccut-studio/` — what it shows, how it edits, and how it talks to Flask.

We teach it as **a journey**: what happens from the moment a user drags in two camera
files to the moment they click Export.

Relevant files (read alongside this doc):

- [../../synccut-studio/src/App.tsx](../../synccut-studio/src/App.tsx) — routes + toaster
- [../../synccut-studio/src/pages/Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx) — **the NLE (most important file)**
- [../../synccut-studio/src/store/useStore.ts](../../synccut-studio/src/store/useStore.ts) — the studio/sync store
- [../../synccut-studio/src/store/useEditorStore.ts](../../synccut-studio/src/store/useEditorStore.ts) — the clip timeline store
- [../../synccut-studio/src/store/useProjectStore.ts](../../synccut-studio/src/store/useProjectStore.ts) — project list
- [../../synccut-studio/src/store/useAuthStore.ts](../../synccut-studio/src/store/useAuthStore.ts) — auth/session
- [../../synccut-studio/src/lib/api.ts](../../synccut-studio/src/lib/api.ts) — the API client
- [../../synccut-studio/src/lib/activeCamera.ts](../../synccut-studio/src/lib/activeCamera.ts) — "who is on at time t?"
- [../../synccut-studio/src/components/ProgramMonitor.tsx](../../synccut-studio/src/components/ProgramMonitor.tsx) — the player
- [../../synccut-studio/src/components/Timeline.tsx](../../synccut-studio/src/components/Timeline.tsx) — the editable timeline
- [../../synccut-studio/src/components/ExportModal.tsx](../../synccut-studio/src/components/ExportModal.tsx) — export UI

---

## 0. The one-sentence version

The frontend is **not** a display page — it is a **client-side NLE**: it manages playback,
draws a multi-track timeline, lets the user blade/move/split/delete clips, resolves "which
camera is on screen right now" (including manual overrides), and finally ships the *exact
edited state* to the backend for export.

The backend decides **offsets**. The frontend decides **the cut**.

---

## 1. How the app is organized

```
synccut-studio/src/
├── main.tsx              ReactDOM.createRoot(<App/>)          ← 10 lines
├── App.tsx               HashRouter + routes + <Toaster/>      ← the shell
├── pages/                full screens: Landing, Login, Dashboard, Workspace, Pricing…
├── components/           reusable UI: ProgramMonitor, Timeline, ExportModal, Inspector…
├── store/                Zustand state (4 stores)
├── lib/                  api.ts (HTTP), activeCamera.ts (pure logic), utils.ts
└── index.css             Tailwind base + design tokens
```

**Stack:** React 18 + TypeScript + Vite, **Zustand** for state, **HashRouter** for routing,
**axios** for HTTP, **dnd-kit** for drag, **Radix UI** for dialogs/menus, **Sonner** for
toasts, **framer-motion** for page transitions.

### 1.1 Why HashRouter (not BrowserRouter)?

`HashRouter` uses `#/workspace/abc` instead of `/workspace/abc`. In a packaged desktop
build the app is served from `file://`/`http://127.0.0.1:<randomport>/` by Flask. A real
path like `/workspace/abc` would make the browser ask the server for a *file* at that path,
which Flask does not serve (`index.html` fallback logic is fragile in a WebView). The `#`
part is never sent to the server, so routing stays entirely client-side. **This is a
packaging requirement disguised as a routing choice** (see doc 02, §desktop).

### 1.2 The route table

From [App.tsx](../../synccut-studio/src/App.tsx#L38-L110):

| Path | Page | Protected? |
|---|---|---|
| `/` | Landing | no |
| `/login` | Login | no |
| `/reset-password` | ResetPassword | no |
| `/pricing` | Pricing | no |
| `/dashboard` | Dashboard | **yes** |
| `/workspace` | Workspace (new project) | **yes** |
| `/workspace/:projectId` | Workspace (existing project) | no wrapper* |
| `*` | → redirect to `/` | — |

`*` Note: `/workspace/:projectId` is **not** wrapped in `ProtectedRoute` in the code —
it relies on the workspace's own `loadSessionProject` call failing with 401/404. Worth
knowing as a small inconsistency (doc 06).

Every route is wrapped in `<PageTransition>` (a framer-motion fade/slide), and
`AnimatePresence mode="wait"` gives clean transitions.

### 1.3 The global toast

```tsx
<Toaster theme="dark" position="bottom-right"
  toastOptions={{ style: { background: '#141418', border: '1px solid #2a2a32', color: '#ededed' } }} />
```
— [App.tsx](../../synccut-studio/src/App.tsx#L126-L137)

This is the app's one notification channel. There are **no `alert()`/`confirm()` calls** —
every user message is a Sonner toast. This is a deliberate product decision (native dialogs
look broken in a WebView and block the render loop).

---

## 2. The four Zustand stores — who owns what

This is the single most important thing to understand before reading the components,
because the app splits its state across **four** stores with clear owners:

| Store | Owns | Lifetime |
|---|---|---|
| `useAuthStore` | user, token, login/Google/logout, `initialize()` | app-wide |
| `useProjectStore` | the dashboard's project list (with a localStorage cache) | app-wide |
| `useStore` | **the sync + program state**: `syncData`, `segments`, `pipeline`, `manualOverrides`, `masterAudioUrl`, `syncReport` | per session |
| `useEditorStore` | **the clip timeline**: `clips` (`EditorClip[]`), playhead, undo/redo | per session |

The last two overlap intentionally: **`useStore` is the semantic model** (cameras, offsets,
AI segments) and **`useEditorStore` is the rendering model** (positioned clips with colors,
sources, transforms). `Workspace.tsx` keeps them in sync.

### 2.1 `useAuthStore` — auth with a safe fallback

`initialize()` runs on app start
([useAuthStore.ts](../../synccut-studio/src/store/useAuthStore.ts#L39-L69)):

1. Read `synccut_auth_token` from `localStorage`. If absent → logged out, done.
2. If present, call `getMeApi()` to **validate** the token against the server.
3. On success, hydrate `user`; on failure, **purge both keys** from localStorage.

Step 2 is the important one: a stale token in localStorage does not leave the UI in a
"half-logged-in" state — it is verified or removed. The token itself is attached to every
request by the axios interceptor (§3.2).

### 2.2 `useProjectStore` — optimistic + offline cache

Every mutation is **optimistic**: it updates local state and writes to localStorage first,
*then* fires the API call inside a `try/catch` that swallows errors
([useProjectStore.ts](../../synccut-studio/src/store/useProjectStore.ts#L85-L110)):

```ts
const updated = [newProj, ...get().projects];
set({ projects: updated });
saveCachedProjects(updated);
try { await createProjectApi(newProj); } catch { /* cached locally */ }
```

The cache key is **per user** (`synccut_projects_<userId|email>`), so two accounts on one
machine never see each other's projects. This makes the dashboard feel instant and survive
a network blip. The cost: the local list can drift from the server (see doc 06).

### 2.3 `useStore` — the studio/sync model (`StudioState`)

This is the big one. Key fields
([useStore.ts](../../synccut-studio/src/store/useStore.ts#L67-L125)):

```ts
sessionId: string;          // crypto.randomUUID() at start
jobId: string | null;       // the polling handle
syncData: CameraSync[];     // per-camera offsets/drift/state from the report
segments: Segment[];        // the program (the cut)
suggestedSegments: Segment[]; // AI suggestion, awaiting "apply"
fps: number;                // default 25
masterCamera, selectedCamera
projectHistory / projectFuture   // undo/redo snapshots
manualOverrides: Record<number, string>;  // timestamp -> camera
pipeline: PipelineState;    // stage/percentage/message/jobStatus
masterAudioUrl; syncReport; files; fileCount; allSources
```

Two types matter here — they are the **contract with the backend report**
([useStore.ts](../../synccut-studio/src/store/useStore.ts#L3-L35)):

```ts
export interface Segment { id?; camera; start; end; confidence?; reason?; source?: 'manual'|'suggested'|'angle'; }

export interface CameraSync {
  source; file?; offset_s; offset_sec?; offset_ms?; offset_samples?; offset_frames?;
  drift_ppm?; drift_ms_per_hour?; link_confidence?; confidence?; psr?;
  window_offsets?; window_std_ms?; state?: 'LOCKED'|'VERIFY'|'WEAK'; warnings?;
  duration_sec?; frame_rate?; waveform_index?; lane_locked?; is_master?;
}
```

Compare these field names to the backend row assembled in
`run_sync_task` ([tasks.py](../../synccut/workers/tasks.py#L197-L223)) — they match
one-to-one. **This is the single most useful cross-check in the whole codebase:** the
frontend type *is* the backend contract.

`sessionId` starts as a random UUID and is later **overwritten with the project id** when
the Workspace loads a saved project
([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L356-L358)) — so the session
directory on disk is named after the project.

### 2.4 `useEditorStore` — the clip timeline model

This store is smaller and purely about *editing* clips
([useEditorStore.ts](../../synccut-studio/src/store/useEditorStore.ts#L3-L19)):

```ts
export interface EditorClip {
  id; name; track; start; duration; color;
  confidence?; sourceIndex?; sourceUrl?; reason?;
  scale; positionX; positionY; rotation; opacity;   // Inspector transform
}
```

It owns `playheadPosition`, `isPlaying`, `clips`, `activeClipId`, `selectedSourceIndex`,
`snapping`, and `undoStack`/`redoStack`.

Its history helper is the cleanest part
([useEditorStore.ts](../../synccut-studio/src/store/useEditorStore.ts#L58-L64)):

```ts
function withHistory(state, update) {
  return { ...update,
    undoStack: [...state.undoStack, snapshot(state)].slice(-MAX_HISTORY),
    redoStack: [] };
}
```

Every mutating action (`moveClip`, `deleteClip`, `splitClipAt`, …) is wrapped by
`withHistory`, so undo/redo comes for free and uniformly. `MAX_HISTORY = 100`.

---

## 3. The API client — one file, one contract

### 3.1 The base URL (the fix that took down the MSIX build)

```ts
// Packaged desktop builds are served by Flask on a dynamically selected port.
// Use the same origin so API calls never hit a stale service on port 5000.
const API_BASE =
  import.meta.env.VITE_API_BASE ??
  (import.meta.env.DEV ? '' : window.location.origin);

const http = axios.create({ baseURL: API_BASE, withCredentials: true });
```
— [api.ts](../../synccut-studio/src/lib/api.ts#L6-L15)

This is worth understanding in full, because it was a real production bug:

- **In dev** (`import.meta.env.DEV`), Vite's proxy handles `/api`, so the base is `''`
  (same-origin, proxied).
- **In a packaged build**, Flask is started by the desktop launcher on a **dynamically
  chosen free port** (doc 02). A hardcoded `http://127.0.0.1:5000` therefore sends requests
  to a port nobody is listening on → network error → the "upload failed" symptom.
- The fix: derive the base from `window.location.origin` — i.e. **whatever origin served
  this page is the backend.** Correct regardless of which port was chosen.
- `import.meta.env.VITE_API_BASE` still allows an override for hosted deployment.

### 3.2 The auth interceptor

```ts
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('synccut_auth_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
```
— [api.ts](../../synccut-studio/src/lib/api.ts#L18-L24)

Every request automatically carries the Bearer token. This is the "Bearer" branch of the
backend's auth resolution order (doc 02). Note it does **not** handle 401 by redirecting —
a 401 simply surfaces to whichever caller made the request (see doc 06).

### 3.3 The function inventory

`api.ts` is the complete backend surface. Grouped:

| Group | Functions |
|---|---|
| Job lifecycle | `uploadFiles`, `startSync`, `getJobStatus`, `cancelJob` |
| Session previews | `getCameraWaveform`, `getCameraThumbnail`, `getSessionMediaUrl` |
| Project (session) file | `loadSessionProject`, `saveSessionProject` |
| AI + export | `runRoughCut`, `exportTimeline` |
| Auth | `loginApi`, `registerApi`, `requestPasswordResetApi`, `resetPasswordApi`, `startGoogleAuthApi`, `pollGoogleAuthApi`, `getMeApi`, `logoutApi` |
| Billing | `getBillingSubscriptionApi`, `createCheckoutApi` |
| Dashboard projects | `getProjectsApi`, `createProjectApi`, `deleteProjectApi`, `updateProjectApi` |
| System | `getStorageInfoApi` (⚠ broken backend — doc 03 §4) |

Two functions deserve a note:

- **`getJobStatus` normalizes progress** client-side. The backend returns raw
  `metadata.current`/`metadata.total`, and this function computes the percentage
  ([api.ts](../../synccut-studio/src/lib/api.ts#L56-L66)):

  ```ts
  const progress = typeof current === 'number' && typeof total === 'number' && total > 0
    ? Math.min(100, Math.max(0, (current / total) * 100)) : null;
  return { ...data, progress } as JobStatusResponse;
  ```

- **`getCameraThumbnail` caches by 10-second bucket** with an LRU-ish cap of 200
  object URLs, revoking the oldest when it overflows
  ([api.ts](../../synccut-studio/src/lib/api.ts#L82-L109)). Without the revoke, the app
  would leak memory over a long editing session — `URL.createObjectURL` results are never
  freed automatically.

---

## 4. The Studio journey — the code path of one edit session

This is the heart of the document. Follow one session.

### 4.1 Step 1 — Import (`handleImport`)

The user clicks **Import Media** (or File → Import). `handleImport`
([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L444-L489)) does, in order:

1. **Validate count** — `if (selected.length < 2 || selected.length > 8)` → toast error.
   The 2–8 constraint is a **product rule enforced at the edge**.
2. **Validate types** — reject files that are neither `video/*`/`audio/*` nor a known
   extension (the `MEDIA_ACCEPT` list).
3. **Optimistic local reset** — clear overrides, sync data, segments; set
   `stage: 'uploading'`; create object URLs for instant local preview:
   ```ts
   state.setAllSources(selected.map((file) => URL.createObjectURL(file)));
   ```
   This is why the Media Pool shows thumbnails *before* the upload finishes — it plays the
   local File objects, not the server's.
4. **Upload** via `uploadFiles(sessionId, files, onProgress)`, reporting progress with
   `setPipeline({ stage: 'uploading', percentage })`.
5. On success → `setJobId(id)` and `stage: 'syncing'`. On failure → `stage: 'failed'`
   with a human message (special-casing HTTP 413 to "files exceed the server upload limit").

It also arms a **confetti flag** (`pendingTimelineCelebration.current = true`) — see §4.4.

### 4.2 Step 2 — Polling (`useEffect` on `jobId`)

Once a `jobId` exists, this effect polls every second until a terminal state
([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L491-L558)). Read it as a
state machine:

```ts
const stage = (metadata.stage as PipelineStage)
  ?? (statusText.toLowerCase().includes('rough cut') || statusText.startsWith('Analyzing ') ... ? 'ai_cutting' : 'syncing');
```

- **In-progress** (`PENDING`/`PROGRESS`) → compute `percentage` from `current/total`,
  set `stage`/`message`.
- **`STALLED`** → message "No progress update for 90 seconds." (backend throttle, doc 02).
- **`FAILURE`/`REVOKED`** → terminal; show the error / "Job cancelled."
- **`SUCCESS`** → **terminal; this is the big branch** (next step).
- **Network error** → keep the last stage, set `jobStatus: 'UNKNOWN'`, message "Cannot
  reach… reconnecting".

Two defensive details: the poll reschedules itself with `setTimeout(poll, 1000)` only while
`!terminal`, and the effect's cleanup sets `cancelled = true` so a nav-away cannot apply a
stale result.

**Note the mapping to the backend's advertised stages** (doc 02): the backend reports
`30% proxying / 60% syncing / 90% AI / 100% ready`; the frontend just renders whatever
`metadata.stage` and `current/total` it receives.

### 4.3 Step 3 — Success → build the program

On `SUCCESS` the response carries `{ sync_data, segments, master_audio_url, loop_error_s }`.
The frontend ([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L506-L536)):

1. Splits the payload: `syncData` (cameras) and `suggested` (AI segments).
2. **Builds a filled program** with `buildProgramDraft(suggested, syncData)` — see §4.4.
3. Stores everything: `setSyncData`, `setSuggestedSegments`, `setSegments(program)`,
   `setMasterAudioUrl`.
4. Computes the **Sync Report card**:

   ```ts
   state.setSyncReport({
     totalSyncSeconds: elapsed, cameraCount: syncData.length,
     lockedCount: syncData.filter(c => c.state === 'LOCKED').length,
     loopErrorMs: Math.abs(Number(response?.loop_error_s ?? 0)) * 1000,
     driftMsPerHour: syncData.reduce((s, c) => s + Math.abs(Number(c.drift_ms_per_hour ?? 0)), 0),
     suggestedCuts: program.length,
   });
   ```
   — [Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L521-L528)

   Every number here maps to a doc-01 concept: `loop_error_s` is the loop-closure error,
   `drift_ms_per_hour` is the drift metric, `state` is the LOCKED/VERIFY/WEAK badge.
5. Sets `stage: 'ready'` **only if a program was produced**, else `'failed'` with a clear
   message ("Sync finished but no video program could be assembled.").
6. Calls `updateProjectStatus(projectId, 'Ready for Export')`.

### 4.4 `buildProgramDraft` — the "editor-proof" AI cut

This pure function ([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L34-L85))
is subtle and important. The AI returns **sparse suggestions** (only where a speaker
change was detected). A timeline cannot have holes. So the function:

1. Computes the session `endTime` from the longest `offset_s + duration_sec`.
2. Collects **boundaries**: `0`, `endTime`, every camera's start/end, and every suggestion's
   start/end.
3. Sorts them and walks each `[boundary[i], boundary[i+1]]` interval, picking a camera for
   the interval's **midpoint**:
   - the **suggested** camera **if** that camera actually has footage at that time
     (`hasSource`), else
   - the **master** camera if it has footage, else
   - any camera that has footage.
4. **Merges adjacent same-camera segments** so the program has no redundant cuts.

The result is a **gap-free, hole-free program** that always falls back to a real camera.
This is the "Zero-State Automation" philosophy in code: the user gets a complete cut to
review, never an empty timeline.

### 4.5 Step 4 — Program → editor clips (the two-store bridge)

The two stores meet in two functions
([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L87-L102 and #L409-L418)):

```ts
// program -> EditorClip[]   (rendering direction)
buildEditorClips(segments, cameras, sources)

// EditorClip[] -> program   (commit direction)
commitEditorClips(clips)  // maps each clip back to a Segment
```

`buildEditorClips` assigns each clip a **stable-ish color** from a fixed palette indexed
by camera, plus transform defaults:

```ts
const CAMERA_COLORS = ['#06b6d4', '#a855f7', '#f97316', '#ec4899', '#22c55e', '#eab308', '#3b82f6', '#14b8a6'];
```

`commitEditorClips` is called **after every timeline edit** — it converts editor clips
back into `Segment[]` and calls `state.editProgramSegments(...)`, which pushes a history
snapshot. So a timeline drag also updates the semantic program and the undo stack.

**The confetti** fires when `pendingTimelineCelebration` is set, the pipeline is `ready`,
and clips exist — a one-shot `canvas-confetti` burst, skipped for users with
`prefers-reduced-motion` ([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L325-L353)).
This is the "moment of delight" at the end of the zero-state flow.

### 4.6 Step 5 — Auto-save + manual save

- **Auto-save** subscribes to `useStore` and debounces 500 ms whenever pipeline is `ready`
  ([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L386-L398)):

  ```ts
  timer = setTimeout(() => { saveSessionProject(state.sessionId, state.toProjectFile())... }, 500);
  ```

  `toProjectFile()` serializes the whole studio state into the `SyncCutProject` shape
  (§5.1). This is why the app survives a reload.
- **Save Project** button calls the same thing immediately, with toasts.

### 4.7 Step 6 — Reload (the restore path)

On mount, `useEffect([projectId])` calls `loadSessionProject(projectId)` and then
**re-hydrates media URLs**, because they are not stored in the project file
([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L356-L383)):

```ts
const sources = project.cameras.map((_, index) => getSessionMediaUrl(projectId, index));
state.setAllSources(sources);
state.setDuration(Math.max(0, ...project.cameras.map(c => c.offset_s + (c.duration_sec ?? 0))));
const restoredClips = buildEditorClips(project.program, project.cameras, sources);
useEditorStore.getState().setClips(restoredClips);
```

The comment in the code literally says "THIS IS THE FIX: Re-hydrate the video URLs from the
backend." **Lesson:** persisted JSON stores *offsets and the cut*, but media is always
re-fetched by index — never serialized.

---

## 5. The two state shapes on the wire

### 5.1 `SyncCutProject` — the save-file format

([useStore.ts](../../synccut-studio/src/store/useStore.ts#L37-L46)):

```ts
export interface SyncCutProject {
  version: 1; fps: number;
  master_audio: string | null; master_camera: string | null;
  cameras: CameraSync[]; program: Segment[];
  settings: { snapping: boolean; overlayCamera: string | null; playbackRate?: number };
  history: Array<{ cameras: CameraSync[]; program: Segment[] }>;
}
```

This is what `saveSessionProject`/`loadSessionProject` read/write, and what the export
route reads as `project.json` (doc 03 §5.7). `version: 1` is a forward-compat marker.

### 5.2 `EditorClip[]` — the export payload

When exporting, the frontend sends `timeline_clips: clips` — the **exact editor state**,
not just the program ([ExportModal.tsx](../../synccut-studio/src/components/ExportModal.tsx#L115-L145)):

```ts
const { clips } = useEditorStore.getState();
...
const { blob, filename } = await exportTimeline(sessionId, option.key, toProjectFile(), manualOverrides, clips);
```

The backend then **overrides** `project.program` with these clips (doc 03 §5.7, step 3).
So the exported file reflects exactly what the user sees on the timeline, including
blade edits, moves, and deletions — not a stale server copy. **This is the "lock-step"
guarantee**, and it is the reason the frontend sends clips as a separate argument rather
than only the project.

---

## 6. The visual layer — ProgramMonitor, Timeline, active-camera logic

### 6.1 `ProgramMonitor` — playback and the seek math

The monitor plays **one** video element and seeks it to match the playhead
([ProgramMonitor.tsx](../../synccut-studio/src/components/ProgramMonitor.tsx#L47-L61)):

```ts
// WHY: The target time in the original video is (Global Time - Sync Offset).
const target = Math.max(0, time - cameraOffset);
if (Math.abs(player.currentTime - target) > 0.05) {
  player.currentTime = Math.min(target, ...);
}
```

**This single line is the frontend twin of the doc-01 offsets.** A timeline position
`time` corresponds to `time - offset_s` inside that camera's own file. The `> 0.05` guard
avoids hammering the seek API on every animation frame.

During playback, a `requestAnimationFrame` loop converts source time back to **global**
time (`sourceTime + cameraOffset`), finds the clip at that global time, and either advances
the playhead or **switches the active clip** ([ProgramMonitor.tsx](../../synccut-studio/src/components/ProgramMonitor.tsx#L85-L115)). That switch is what makes the program *cut* between
cameras during playback.

The monitor also applies the Inspector transform live:

```ts
const activeTransform = `translate(${positionX}px, ${positionY}px) rotate(${rotation}deg) scale(${scale/100})`;
```
— [ProgramMonitor.tsx](../../synccut-studio/src/components/ProgramMonitor.tsx#L44-L45)

### 6.2 `Timeline` — a real editing surface

The active timeline ([Timeline.tsx](../../synccut-studio/src/components/Timeline.tsx)) is a
hand-built NLE strip with:

- **A timecode ruler** with adaptive tick spacing — `tickStep` picks the first of
  `[5,10,15,30,60,120,300,600]` seconds whose on-screen width ≥ 100 px
  ([Timeline.tsx](../../synccut-studio/src/components/Timeline.tsx#L192-L195)). Zoom-aware
  rulers are the difference between a toy and a tool.
- **Two tracks**: V1 (Program, video clips) and A1 (Audio, a generated waveform background
  built as an inline SVG data-URL, `makeWaveformSvg()`).
- **`pixelsPerSecond`** zoom with a slider (0.25–90) and a **Fit** button resetting
  `zoom` to `null` (which falls back to `fitScale = (viewportWidth - LABEL_WIDTH)/duration`).
- **Drag-to-move** via dnd-kit, restricted to the horizontal axis
  (`restrictToHorizontalAxis`) and **snapped to 0.5 s** when snapping is on
  ([Timeline.tsx](../../synccut-studio/src/components/Timeline.tsx#L123-L131)):

  ```ts
  const rawStart = Math.max(0, clip.start + event.delta.x / pixelsPerSecond);
  const start = snapping ? Math.round(rawStart * 2) / 2 : rawStart;
  ```
- **Tools**: `select` (V) and `blade` (S). In blade mode a click on the track calls
  `splitClipAt(position)`.
- **Keyboard**: Ctrl/Cmd+Z undo, Ctrl/Cmd+Shift+Z / Ctrl+Y redo, Delete/Backspace deletes
  the active clip, S/V switch tools. The listener reads the store via
  `useEditorStore.getState()` inside the handler — the comment explains *why*
  ([Timeline.tsx](../../synccut-studio/src/components/Timeline.tsx#L154-L190)):

  > Access the store directly to avoid stale closures and prevent the listener from
  > re-binding 60 times a second

  This is a genuinely important React pattern: putting `clips` in the effect deps would
  re-attach the window listener on every frame. Reading fresh state inside the handler
  keeps the effect dependent only on the stable `onCommitClips` callback.
- The **playhead** is a 1-px cyan line with a diamond handle, positioned at
  `LABEL_WIDTH + playheadPosition * pixelsPerSecond`.

### 6.3 `getActiveCamera` — the override resolver

[activeCamera.ts](../../synccut-studio/src/lib/activeCamera.ts) answers "who is on at time
`t`?" and encodes the override rule in four lines:

```ts
export function getActiveCamera(t, segments, overrides) {
  const keys = Object.keys(overrides).map(Number).filter(k => k <= t).sort((a, b) => a - b);
  const k = keys[keys.length - 1];
  if (k !== undefined && segIndex(k, segments) === segIndex(t, segments)) return overrides[k];
  return segIndex(t, segments) >= 0 ? segments[segIndex(t, segments)].camera : null;
}
```

The rule: **the most recent override at or before `t` wins, but only within the same AI
segment** (the one that contained the override timestamp). Outside that segment, the AI
decision resumes. This is a clean, minimal way to say "user override beats AI locally,
AI wins globally."

### 6.4 Multi-camera grid and the active-camera glow

The design rule for a multi-view layout — **active camera at full opacity with a cyan
glow, inactive dimmed** — is part of the product's visual language. (The interactive grid
lives in `components/MultiView.tsx`, which sizes as 1 / 2 / 2×2 / 3×3 by `fileCount`.)

⚠ **Important caveat for a reader:** `MultiView.tsx`, `WaveformTimeline.tsx`,
`CapCutTimeline.tsx`, `DropZone.tsx`, `ExportPanel.tsx`, `JobStatusPanel.tsx`, and
`PipelineStatus.tsx` all **exist in the repo but are not imported anywhere** in the current
app. A grep for their imports returns nothing. The **active** Workspace uses exactly four
components: `ProgramMonitor`, `Timeline`, `OnboardingTour`, and `ExportModal`
([Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx#L9-L14)). The others are
earlier iterations kept on disk. This is documented as technical debt in doc 06 — do not
assume a file is live just because it compiles.

---

## 7. Export UI — tier gating and the weak-sync guard

`ExportModal` ([ExportModal.tsx](../../synccut-studio/src/components/ExportModal.tsx)) is
small but encodes three product rules:

1. **Format gating by tier.** FCPXML and AAF are `proOnly: true`. A free user clicking them
   is `navigate('/pricing')`'d instead
   ([ExportModal.tsx](../../synccut-studio/src/components/ExportModal.tsx#L100-L113)).
2. **Weak-sync confirmation.** It counts LOCKED / VERIFY / WEAK cameras and, if any need
   review, the first click flips to a **"Export anyway"** confirmation instead of
   downloading ([ExportModal.tsx](../../synccut-studio/src/components/ExportModal.tsx#L124-L127)):

   ```ts
   if (needsReview && !confirmWeak) { setConfirmWeak(true); return; }
   ```
3. **Multi-format download.** It loops the selected formats and triggers one browser
   download each via a temporary `<a download>` element.

The format list maps directly to the backend dispatcher (doc 03 §5.7):

| Modal option | `key` sent | Backend branch |
|---|---|---|
| FCPXML | `fcpxml` | default → `timeline.fcpxml` |
| EDL | `edl` | `timeline.edl` |
| AAF | `aaf` | `timeline.aaf` |
| Sync Audit (PDF) | `audit_pdf` | `sync_audit_report.pdf` |

---

## 8. Design tokens and the "premium suite" look

Two parallel color systems exist, and knowing which is which saves confusion:

- **Tailwind tokens** (semantic): `bg-background` `#0a0a0c`, `bg-panel` `#141418`,
  `border-border` `#2a2a32`, and `accent`. **`--accent` is `#06b6d4`** (cyan-500) in
  [index.css](../../synccut-studio/src/index.css#L17).
- **Inline hex `#00E5FF`** (bright cyan) used directly in some components (e.g. ExportModal,
  the glow states). So the app has **two cyan accents** — `#06b6d4` token vs `#00E5FF`
  literal. This is a known inconsistency (doc 06).

Background is always the near-black `#0a0a0c`; the aesthetic helpers
(`.glass-panel`, `.glass-panel-glow`, `.cyan-gradient-text`) are in
[index.css](../../synccut-studio/src/index.css#L30-L50).

---

## 9. Known issues in the frontend (carry these forward)

| Issue | Where | Impact |
|---|---|---|
| Two overlapping stores (`useStore` + `useEditorStore`) synced manually | Workspace | Easy to desync; edits must go through `commitEditorClips` |
| Orphaned legacy components (MultiView, CapCutTimeline, …) | `components/` | Dead code; confusing for newcomers |
| Two cyan accents (`#06b6d4` vs `#00E5FF`) | tokens vs inline | Visual inconsistency |
| `getStorageInfoApi` calls a broken backend route | `api.ts` | Would 500 if called |
| Token is only validated at boot; a 401 mid-session does not auto-logout | `api.ts` interceptor | Silent failures on expired tokens |
| `/workspace/:projectId` is not wrapped in `ProtectedRoute` | `App.tsx` | Relies on the load call failing |
| Project list is optimistic + localStorage-cached | `useProjectStore` | Local list can drift from the server |

---

## 10. Self-check — can you answer these without re-reading?

1. Why `HashRouter` and not `BrowserRouter` in a packaged desktop build?
2. What is the difference between `useStore.syncData` and `useEditorStore.clips`?
3. Why does `api.ts` compute `API_BASE` from `window.location.origin`?
4. What does `buildProgramDraft` guarantee that a raw AI suggestion list does not?
5. In `ProgramMonitor`, why is the seek target `time - cameraOffset`?
6. What is the exact override rule in `getActiveCamera`?
7. Why does `ExportModal` pass `clips` separately from `toProjectFile()`?
8. Why does the timeline keyboard handler read the store inside the handler instead of
   depending on `clips`?

If you can answer all eight, you understand the Studio.

---

## Where to go next

Doc 05 zooms into **persistence** — the SQLite models, the session directories, ownership,
and the tier state this UI reads and writes. Doc 06 collects the trade-offs and debt hinted
at in §9 above.
