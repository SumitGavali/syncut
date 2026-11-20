# SyncCut Studio — Codebase Mastery Knowledge Base

This folder is the complete technical learning base for the **actual** SyncCut Studio
implementation. It teaches the repository from first principles, in a reading order that
follows how data actually flows through the product.

Nothing here is a generic architecture template. Every claim is anchored to a real file,
function, constant, or test in this repository.

---

## How to read this (start here)

If you have never seen the project, read in this order. Each document assumes only the
previous ones.

| Order | Document | What you will be able to explain afterwards |
|---|---|---|
| 0 | **README.md** (this file) | The whole system on one page, and where everything lives |
| 1 | [01-audio-synchronization-mathematics.md](./01-audio-synchronization-mathematics.md) | How two recordings are aligned to the sample, and why the math works |
| 2 | [02-backend-architecture-and-orchestration.md](./02-backend-architecture-and-orchestration.md) | How an HTTP upload turns into a finished job |
| 3 | [03-media-processing-caching-export-pipeline.md](./03-media-processing-caching-export-pipeline.md) | How media is decoded, cached, mixed, and exported |
| 4 | [04-frontend-studio-experience-and-timeline-editing.md](./04-frontend-studio-experience-and-timeline-editing.md) | How the React NLE works and how it talks to the backend |
| 5 | [05-data-model-and-persistence-layer.md](./05-data-model-and-persistence-layer.md) | What is stored, where, and in what shape |
| 6 | [06-engineering-trade-offs-and-production-readiness.md](./06-engineering-trade-offs-and-production-readiness.md) | Where the system is strong, heuristic, or fragile |
| 7 | [07-work-division-and-roles.md](./07-work-division-and-roles.md) | How the work splits across four engineers, module by module |

Read them in order the first time. After that they work as reference documents.

---

## The system in one page

SyncCut Studio takes **2–8 camera recordings of the same event** (separate phones,
cameras, or audio recorders), finds the **exact time offset** of each using their audio,
then uses an **AI active-speaker model** to build an **automated rough cut** — with no
timecode, clap, or slate.

```
   user drops 2-8 clips
            |
            v
  +---------------------------+        React (synccut-studio)
  |  Workspace.tsx            |        Zustand stores, HashRouter
  |  handleImport()           |
  +-------------+-------------+
                | POST /api/upload  (multipart)
                v
  +---------------------------+        Flask (synccut/api)
  |  routes.py : upload_files |        app factory, blueprints
  |  save -> spawn worker     |
  +-------------+-------------+
                | daemon thread (desktop) or Celery (cloud)
                v
  +---------------------------+        Pipeline (synccut/workers/tasks.py)
  |  run_sync_task()          |
  |    1. extract 16 kHz mono |  <-- ffmpeg
  |    2. GCC-PHAT / sync_core|  <-- synccut/core
  |    3. global offset solve |
  |    4. master mixdown      |
  |  run_ai_cut_task()        |
  |    5. active speaker AI   |  <-- synccut/ai
  +-------------+-------------+
                | writes session artifacts
                v
     sync_report.json, master_mix.wav, switches.json
                |
                v
  +---------------------------+        Frontend polls GET /api/job/status
  |  WaveformTimeline.tsx     |        -> renders the program, allows edits
  |  ExportModal.tsx          |        -> POST /api/export/timeline
  +---------------------------+
                |
                v
        FCPXML / EDL / AAF / PDF
```

### The five pipelines, in plain words

1. **Ingest** — clips are uploaded, owned by a user, stored in a per-session directory.
2. **Decode** — ffmpeg converts everything to mono 16 kHz PCM with an 80 Hz high-pass.
3. **Align** — cross-correlation estimates a coarse offset, 8-second windows refine it and
   measure drift, and a weighted least-squares solve puts every camera on one timeline.
4. **Cut** — a Light-ASD ONNX model scores who is speaking in each camera; a state machine
   converts those scores into camera-switch segments.
5. **Deliver** — the segments become an FCPXML/EDL/AAF/PDF export, and the browser renders
   an editable program timeline.

---

## Where everything lives

### Backend (Python, package `synccut/`)

| Path | Role |
|---|---|
| [../../app.py](../../app.py) | Thin WSGI entry point -> `create_app()` |
| [../../desktop_launcher.py](../../desktop_launcher.py) | PyWebView desktop entry point (MSIX/Store) |
| [../../synccut/api/factory.py](../../synccut/api/factory.py) | App factory, CORS, secret key, error handler, SPA serving |
| [../../synccut/api/routes.py](../../synccut/api/routes.py) | Every API route + the in-process job model |
| [../../synccut/api/auth.py](../../synccut/api/auth.py) | Password reset (SMTP) + Google OAuth with PKCE |
| [../../synccut/api/billing.py](../../synccut/api/billing.py) | Stripe checkout + webhook |
| [../../synccut/api/db.py](../../synccut/api/db.py) | SQLAlchemy models, migration, auth, tiers |
| [../../synccut/api/tier_limits.py](../../synccut/api/tier_limits.py) | Route decorators for plan gating |
| [../../synccut/api/job_manager.py](../../synccut/api/job_manager.py) | Legacy ThreadPoolExecutor job runner |
| [../../synccut/core/sync_core.py](../../synccut/core/sync_core.py) | **Production sync engine** (fast path) |
| [../../synccut/core/sync_engine.py](../../synccut/core/sync_engine.py) | **GCC-PHAT reference engine** + global solver |
| [../../synccut/core/confidence.py](../../synccut/core/confidence.py) | Feature extraction, calibration, ECE/AUC |
| [../../synccut/core/drift.py](../../synccut/core/drift.py) | Windowed drift analysis + correction |
| [../../synccut/core/robustness.py](../../synccut/core/robustness.py) | Pre-flight media integrity checks |
| [../../synccut/core/camera_switch.py](../../synccut/core/camera_switch.py) | Audio-energy camera switching (non-AI path) |
| [../../synccut/core/quota.py](../../synccut/core/quota.py) | Plan limits + enforcement |
| [../../synccut/media/extract.py](../../synccut/media/extract.py) | ffmpeg audio extraction + ffprobe helpers |
| [../../synccut/media/mixdown.py](../../synccut/media/mixdown.py) | Builds `master_mix.wav` from N stems |
| [../../synccut/media/proxy_gen.py](../../synccut/media/proxy_gen.py) | 720p H.264 proxies for browser scrubbing |
| [../../synccut/ai/rough_cut.py](../../synccut/ai/rough_cut.py) | AI active-speaker rough cut state machine |
| [../../synccut/ai/face_tracker.py](../../synccut/ai/face_tracker.py) | ONNX runner + Haar face detection |
| [../../synccut/export/timeline_builder.py](../../synccut/export/timeline_builder.py) | OTIO timeline -> FCPXML/EDL with patches |
| [../../synccut/export/fcp7_exporter.py](../../synccut/export/fcp7_exporter.py) | Hand-written FCP7 XML (xmeml v4) |
| [../../synccut/export/switch_timeline.py](../../synccut/export/switch_timeline.py) | Rough-cut single-track timeline |
| [../../synccut/workers/tasks.py](../../synccut/workers/tasks.py) | Shared pipeline functions + Celery tasks |
| [../../synccut/workers/celery_app.py](../../synccut/workers/celery_app.py) | Celery app configuration |
| [../../synccut/workers/job_control.py](../../synccut/workers/job_control.py) | Redis progress + cancellation |
| [../../synccut/paths.py](../../synccut/paths.py) | All path resolution (frozen / MSIX / dev) |
| [../../synccut/config.py](../../synccut/config.py) | Every numeric threshold in one place |

### Frontend (React + TypeScript, `synccut-studio/`)

| Path | Role |
|---|---|
| [../../synccut-studio/src/App.tsx](../../synccut-studio/src/App.tsx) | HashRouter routes + Sonner toaster |
| [../../synccut-studio/src/lib/api.ts](../../synccut-studio/src/lib/api.ts) | The only HTTP client; all endpoints |
| [../../synccut-studio/src/store/useStore.ts](../../synccut-studio/src/store/useStore.ts) | **Master NLE store** (sync, program, pipeline) |
| [../../synccut-studio/src/store/useEditorStore.ts](../../synccut-studio/src/store/useEditorStore.ts) | Editor clips + undo/redo |
| [../../synccut-studio/src/store/useAuthStore.ts](../../synccut-studio/src/store/useAuthStore.ts) | Auth + Google login polling |
| [../../synccut-studio/src/store/useProjectStore.ts](../../synccut-studio/src/store/useProjectStore.ts) | Dashboard project list |
| [../../synccut-studio/src/pages/Workspace.tsx](../../synccut-studio/src/pages/Workspace.tsx) | The NLE page; upload -> poll -> render |
| [../../synccut-studio/src/components/MultiView.tsx](../../synccut-studio/src/components/MultiView.tsx) | Multi-camera monitor with active-camera glow |
| [../../synccut-studio/src/components/WaveformTimeline.tsx](../../synccut-studio/src/components/WaveformTimeline.tsx) | Program timeline with cut editing |
| [../../synccut-studio/src/components/ExportModal.tsx](../../synccut-studio/src/components/ExportModal.tsx) | Export format chooser |

### Build, packaging and distribution

| Path | Role |
|---|---|
| [../../build.spec](../../build.spec) | **Primary** PyInstaller spec (`SyncCutStudio.exe`, windowed) |
| [../../desktop_launcher.py](../../desktop_launcher.py) | What runs when the exe starts |
| [../../AppxManifest.xml](../../AppxManifest.xml) | MSIX / Microsoft Store identity and capabilities |
| [../../packaging_hooks/pyi_rth_synccut.py](../../packaging_hooks/pyi_rth_synccut.py) | PyInstaller runtime hook (CWD + env) |
| [../../Dockerfile](../../Dockerfile) | Multi-stage production image (Render) |
| [../../infra/synccut.spec](../../infra/synccut.spec) | Legacy console spec (`SyncCut.exe`) |
| [../../render.yaml](../../render.yaml) | Render blueprint: api + worker + redis + postgres |
| [../../.github/workflows/ci.yml](../../.github/workflows/ci.yml) | CI: pytest on Python 3.10–3.13 + benchmark |

---

## The one-paragraph version of "what happens when I press Sync"

You drop 2–8 files. `Workspace.handleImport()` validates them, seeds the Zustand store,
and POSTs them to `/api/upload`. `routes.upload_files()` saves them into
`<LOCALAPPDATA>/SyncCutStudio/sessions/<session_id>/` with `01_`…`08_` prefixes, records
ownership in `.owner.json`, and spawns a daemon thread that calls
`_run_local_full_pipeline_job()`. That thread runs `run_sync_task()` (decode -> align ->
`sync_report.json` + `master_mix.wav`) and then `run_ai_cut_task()` (AI -> `switches.json`),
writing progress into the in-memory `LOCAL_JOBS` dict. The browser polls
`GET /api/job/status` once per second; on `SUCCESS` it reads `sync_data` and `segments`,
builds a program draft, and unlocks the timeline. From there the user edits, and
`POST /api/export/timeline` renders FCPXML/EDL/AAF/PDF through
`export/timeline_builder.py` and `export/fcp7_exporter.py`.

That paragraph is the spine of documents 01–05.

---

## Reading conventions used in this knowledge base

- **Verified** means a line of code or a test proves the statement.
- **Inferred** means it is a reasonable engineering reading when intent was not documented.
- Code references are relative links so they work on GitHub and in an editor.
- Numeric constants are quoted with their source file so you can always re-check them.
- Where code and older documentation disagree, **the code wins**, and the divergence is
  called out explicitly.

---

## Obvious interview questions

> These are the questions a senior engineer or technical interviewer will ask in the first
> 30 minutes. Every answer is grounded in an actual file or function.

---

**Q: Is SyncCut stateless or stateful?**

**A: Hybrid — three layers with different durability guarantees.**

| Layer | State | Durability |
|---|---|---|
| HTTP API | Stateless — Bearer token; no server-side session for auth | Lives in `localStorage` on the client |
| `LOCAL_JOBS` dict | In-memory per-process (see `routes.py`) | Lost on process restart |
| `SESSIONS` dict | In-memory per-process (see `routes.py`) | Lost on process restart |
| SQLite / PostgreSQL | Durable relational store (see `db.py`) | Survives restarts indefinitely |

The HTTP layer is fully stateless: every request carries a Bearer token and the route
re-authenticates it via `db.get_user_by_token()`. Job progress and media paths are held
in the in-memory dicts, so a server crash clears them. User accounts, projects, and
subscription rows are written to the database and persist.

---

**Q: Where does user account data go?**

**A: SQLite in desktop/MSIX mode; PostgreSQL in cloud/Render mode — decided by `db.py:_database_url()`.**

```
desktop  → %LOCALAPPDATA%\SyncCutStudio\synccut.db  (SQLite)
cloud    → DATABASE_URL env var                      (PostgreSQL, Render)
```

`_database_url()` checks (in order):
1. `is_frozen()` or `SYNCCUT_DESKTOP=1` → builds the SQLite path via `paths.get_db_dir()`
2. `DATABASE_URL` env var is set → uses PostgreSQL (rewrites `postgres://` → `postgresql://` for SQLAlchemy 2.x compatibility)
3. Neither → SQLite fallback (development)

See `synccut/api/db.py` → `_database_url()`.

---

**Q: Where do uploaded videos go?**

**A: `%LOCALAPPDATA%\SyncCutStudio\sessions\<session_id>\`, with ordered prefixes.**

```
%LOCALAPPDATA%\SyncCutStudio\sessions\
  └── <session_id>\
        ├── .owner.json          ← {"user_id": "usr_xxx"}
        ├── 01_<original_name>   ← first uploaded file
        ├── 02_<original_name>   ← second uploaded file
        │   …up to 08_…
        ├── <name>_16k.wav       ← decoded mono PCM per clip
        ├── sync_report.json
        ├── master_mix.wav
        ├── switches.json
        └── proxy\
              └── <name>_proxy.mp4
```

Files are written by `routes.upload_files()`. The prefix `01_`…`08_` establishes a
deterministic camera order. `.owner.json` is written by `_claim_session()` (see
`routes.py`) and gates all subsequent file access.

---

**Q: Where does the SQLite DB live and who creates it?**

**A: `paths.py:get_db_dir()` → `%LOCALAPPDATA%\SyncCutStudio\synccut.db`; `init_db()` calls `Base.metadata.create_all()`.**

```python
# paths.py (paraphrased)
def get_db_dir() -> Path:
    return get_app_data_dir() / "synccut.db"

# db.py (paraphrased)
def init_db(engine):
    Base.metadata.create_all(engine)
```

`init_db()` is called once at app startup from `factory.py`. It is idempotent: if the
tables already exist, `create_all()` does nothing. `_ensure_legacy_columns()` runs
afterwards to add columns that were added post-launch (no Alembic; uses raw
`ALTER TABLE ADD COLUMN IF NOT EXISTS`).

---

**Q: Is there a session in the HTTP sense?**

**A: No Flask session cookie is used for authentication. Auth is stateless Bearer token. The Flask session is used *only* for Google OAuth PKCE state.**

- Auth: `useAuthStore.ts` stores the token in `localStorage`. Every request adds
  `Authorization: Bearer <token>`. The route decorator `require_auth` (see `routes.py`)
  calls `db.get_user_by_token()` on every request — no cookie, no session table.
- Google OAuth: During the OAuth redirect dance, `auth.py` stores `oauth_state` and
  `nonce` in the Flask session cookie. It is cleared after the callback completes.
  This is the *only* use of `flask.session`.

---

**Q: How does auth work end-to-end?**

**A: Email/password → token stored in DB → Bearer header on every request.**

```
Sign up:   POST /api/register
           → db.create_user()
           → generates token, stores in users.token (SQLite/PG)
           → returns {token, user}
           → frontend stores token in localStorage

Sign in:   POST /api/login
           → db.authenticate_user(email, password)
           → verifies bcrypt hash (hashed_password column)
           → returns existing users.token
           → frontend stores in localStorage

Every API: Authorization: Bearer <token>
           → routes.require_auth decorator
           → db.get_user_by_token(token)
           → sets flask.g.current_user
           → route handler uses g.current_user
```

See `synccut/api/db.py` → `authenticate_user()`, `get_user_by_token()`;  
see `synccut/api/routes.py` → `require_auth`.

---

**Q: What is a "session" vs a "project"?**

**A: Different concepts that share the same ID value.**

| Concept | What it is | Where it lives |
|---|---|---|
| `session_id` | Filesystem working-directory key for one upload batch | Directory name under `sessions/` |
| `project` | SQLite row with metadata (name, status, camera count, etc.) | `projects` table in `db.py` |

They are linked: `create_user_project()` accepts an optional `session_id`; when not
provided it falls back to `session_id = project_id`. This means the directory name and
the database row share the same UUID. A session dir can exist before any project row is
written (the upload creates the dir; the frontend creates the project row separately via
`PUT /api/session/<id>/project`).

---

**Q: What happens to data if the app crashes mid-sync?**

**A: Job progress is lost; files on disk survive; the job cannot be resumed.**

| Data | Fate after crash |
|---|---|
| `LOCAL_JOBS[job_id]` | **Lost** — in-memory dict is gone |
| Session directory on disk | **Survives** — written by OS, not held in memory |
| Partially written `sync_report.json` | May be corrupt or absent |
| SQLite project row | **Survives** — committed writes persist |

The user will see a stale or missing status on the next poll. They must re-upload and
re-run the sync. There is no checkpoint/resume mechanism in the desktop in-process path.
In cloud mode, Celery + Redis holds task state externally, but Render's ephemeral
filesystem means session files can still be lost on dyno restart.

---

**Q: Can two users share a project?**

**A: No. `.owner.json` ties a session directory to exactly one `user_id`.**

`_claim_session()` in `routes.py` writes `{"user_id": g.current_user.id}` to
`.owner.json` on the first upload. Every subsequent file-serving route reads this file
and compares `owner["user_id"] == g.current_user.id`. Mismatch → 403.

There is no sharing, collaboration, or team model. Project rows in SQLite also carry a
`user_id` FK and `get_user_projects()` filters by the authenticated user.

---

**Q: What is the TEMP dir issue and why does upload fail with `OSError 28`?**

**A: Werkzeug buffers multipart uploads to `TEMP` before moving them to the session dir. In MSIX, `TEMP` pointed to sandboxed space that filled up. `paths.py` now redirects it.**

`OSError 28` = `ENOSPC` (no space left on device). The root cause:

1. Werkzeug's `save()` for `FileStorage` first writes the whole upload to `tempfile.gettempdir()`.
2. In an MSIX-packaged app, Windows sets `TEMP`/`TMP` to a virtualised sandbox path with
   a small quota.
3. Large video files exhausted that quota before the temp file could be moved to the real
   session directory.

**Fix** (in `paths.py`):
```python
# paths.py (paraphrased)
tmp_dir = get_app_data_dir() / "tmp"
tmp_dir.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(tmp_dir)
os.environ["TMP"]  = str(tmp_dir)
import tempfile
tempfile.tempdir = str(tmp_dir)
```

This runs at import time so that by the time Werkzeug touches `tempfile.gettempdir()`,
it returns `%LOCALAPPDATA%\SyncCutStudio\tmp` — a path with ample quota on the user's
main drive.

---

## Environment variables reference

> Variables are read at startup. Missing required variables in cloud mode cause startup
> failure or degraded functionality; desktop mode has safe defaults for most of them.

| Variable | Purpose | If missing | Mode |
|---|---|---|---|
| `SECRET_KEY` / `SYNCCUT_SECRET_KEY` | Flask secret key for signing cookies and CSRF tokens. `factory.py` checks both names; falls back to auto-generating a persistent key stored in `%LOCALAPPDATA%\SyncCutStudio\.flask_secret_key`. | Auto-generated on first launch (desktop); should always be set in cloud | Both |
| `DATABASE_URL` | Full PostgreSQL DSN (e.g. `postgresql://user:pass@host/db`). Triggers cloud/PostgreSQL mode in `db.py:_database_url()`. | Falls back to local SQLite — correct for desktop, wrong for cloud | Cloud only |
| `GOOGLE_CLIENT_ID` | OAuth 2.0 client ID for Google Sign-In. Used by `auth.py` to initiate and validate the OAuth flow. | Google Sign-In button is hidden / returns 500 | Both (optional) |
| `GOOGLE_CLIENT_SECRET` | OAuth 2.0 client secret. Paired with `GOOGLE_CLIENT_ID`. | Same as above | Both (optional) |
| `STRIPE_SECRET_KEY` | Stripe API key for creating checkout sessions and managing subscriptions. Used by `billing.py`. | Billing routes return 500; free tier still works | Cloud (optional) |
| `STRIPE_WEBHOOK_SECRET` | Used to verify the HMAC signature on incoming Stripe webhook events. If wrong, all webhook calls are rejected. | Subscription upgrades from Stripe webhooks silently fail | Cloud (optional) |
| `SMTP_HOST` | Outgoing mail server hostname (e.g. `smtp.sendgrid.net`). Used by `auth.py` for password-reset emails. | Password reset emails are not sent | Cloud (optional) |
| `SMTP_PORT` | SMTP port (typically `587` for STARTTLS). | Defaults to `587` if unset | Cloud (optional) |
| `SMTP_USER` | SMTP authentication username. | Password reset emails are not sent | Cloud (optional) |
| `SMTP_PASS` | SMTP authentication password / API key. | Password reset emails are not sent | Cloud (optional) |
| `SMTP_FROM` | The `From:` address on outgoing emails. | Falls back to `SMTP_USER` or a hardcoded default | Cloud (optional) |
| `SYNCCUT_DESKTOP` | Set to `"1"` automatically by `desktop_launcher.py` before importing Flask. Forces SQLite mode and disables Celery. `db.py:_database_url()` treats this as equivalent to `is_frozen()`. | Not set in cloud; must not be set on Render | Desktop only |
| `REDIS_URL` | Redis DSN for Celery broker and result backend (e.g. `redis://localhost:6379/0`). Read by `celery_app.py`. | Celery workers cannot start; cloud job queue fails | Cloud only |

---

## Data-flow for every major operation

| Operation | Frontend call | Route / handler | Storage written |
|---|---|---|---|
| **Sign up** | `POST /api/register` | `db.create_user()` | `users` row + `subscriptions` row in SQLite/PG |
| **Sign in** | `POST /api/login` | `db.authenticate_user()` | `users.token` updated in SQLite/PG |
| **Google sign-in** | `GET /api/auth/google` → redirect → `GET /api/auth/google/callback` | `auth.py` OAuth flow | `users` row (upsert on `google_sub`), Flask session cleared |
| **Import media** | `POST /api/upload` (multipart) | `routes.upload_files()` | Session dir on disk + `.owner.json` + `LOCAL_JOBS[job_id]` (memory) |
| **Poll status** | `GET /api/job/status?job_id=<id>` | `routes.job_status()` | Reads `LOCAL_JOBS` (memory only); no write |
| **Save project** | `PUT /api/session/<id>/project` | `routes.session_project()` | `projects` row in SQLite/PG (upsert via `session.merge()`) |
| **Load project** | `GET /api/session/<id>/project` | `routes.session_project()` | No write; reads `projects` row |
| **List projects** | `GET /api/projects` | `routes.projects()` | No write; calls `db.get_user_projects()` |
| **Export** | `POST /api/export/timeline` | `routes.export_timeline()` | Writes FCPXML/EDL/AAF/PDF file to session dir; returns file download |
| **Stripe checkout** | `POST /api/billing/checkout` | `billing.py` | Creates Stripe session; no local DB write yet |
| **Stripe webhook** | Stripe → `POST /api/billing/webhook` | `billing.py` | Updates `subscriptions` row in SQLite/PG |
| **Password reset request** | `POST /api/auth/forgot-password` | `auth.py` | Writes reset token to `users` row; sends SMTP email |
| **Delete project** | `DELETE /api/session/<id>` | `routes.delete_session()` | Removes `projects` row; deletes session dir from disk |

---

## Quick glossary

| Term | Definition |
|---|---|
| **GCC-PHAT** | Generalised Cross-Correlation with Phase Transform. The core algorithm used in `sync_engine.py` to estimate the time offset between two audio signals. PHAT whitening flattens the frequency spectrum before computing the cross-correlation, making it robust to coloured noise. |
| **master mix** | `master_mix.wav` — a mono WAV file produced by `media/mixdown.py` that blends all camera audio streams after alignment. It is used as the reference waveform displayed in `WaveformTimeline.tsx`. |
| **session_id** | A UUID string that names the per-upload filesystem working directory under `%LOCALAPPDATA%\SyncCutStudio\sessions\`. It is generated by the client (`useStore.ts`) and sent with the upload request. |
| **project_id** | The primary key of a `projects` row in the database. In practice `project_id == session_id` because `create_user_project()` falls back to `session_id` when no separate ID is supplied. |
| **LOCAL_JOBS** | A module-level `dict` in `routes.py` that maps `job_id → {status, progress, result, …}`. It is the job-tracking mechanism for the desktop in-process worker. It is not persisted; a process restart clears it. |
| **.owner.json** | A tiny JSON file written by `_claim_session()` into the session directory: `{"user_id": "usr_xxx"}`. Every file-serving route reads it and returns 403 if the authenticated user does not match. It is the sole access-control mechanism for session files. |
| **SESSIONS dict** | A module-level `dict` in `routes.py` that caches decoded media paths, signal arrays, and analysis results for the current session. Like `LOCAL_JOBS`, it is in-memory and lost on restart. |
| **_MEIPASS** | `sys._MEIPASS` — the temporary directory PyInstaller extracts bundled files into at runtime. `paths.py:is_frozen()` checks for its presence to detect packaged execution. All resource paths that differ between dev and packaged mode use this check. |
| **is_frozen()** | Helper in `paths.py`: returns `True` when running inside a PyInstaller bundle (`hasattr(sys, '_MEIPASS')`). Used to switch between development paths and production paths for ffmpeg, model files, and the database. |
| **MSIX** | Microsoft's modern Windows packaging format (replaces MSI). SyncCut is distributed as an `.msix` bundle for the Microsoft Store. The package is defined by `AppxManifest.xml`. MSIX imposes filesystem virtualisation and sandbox restrictions that motivated the `TEMP` dir fix in `paths.py`. |
| **AppxManifest.xml** | The MSIX package manifest. Declares the app's identity (`Publisher`, `Version`), display name, capabilities (internet access, etc.), file-type associations, and the executable entry point. Required by the Windows packaging tools. |
| **tier** | The user's subscription level, stored in `subscriptions.plan` (values: `free`, `pro`, `studio`). Checked by decorators in `tier_limits.py` to gate features such as camera count, export formats, and AI cut access. |
| **Celery** | Distributed task queue library used in cloud/Render mode. `workers/celery_app.py` configures it with Redis as broker and result backend. `run_sync_task` and `run_ai_cut_task` are decorated as `@celery_app.task`. Not used in desktop mode. |
| **OTIO** | OpenTimelineIO — an open interchange format for editorial timelines (from Pixar / Apple). `export/timeline_builder.py` constructs an OTIO `Timeline` object and then adapts it to FCPXML or EDL via OTIO's adapter system. |
| **proxy** | A low-resolution (`720p`, H.264) transcode of each camera clip, generated by `media/proxy_gen.py` and stored in `sessions/<session_id>/proxy/`. The browser loads proxies for real-time scrubbing in `MultiView.tsx` and `WaveformTimeline.tsx`; original files are only used for export. |
