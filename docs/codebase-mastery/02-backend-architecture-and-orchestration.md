# Order 2 — Backend Architecture and Orchestration

This document explains how an HTTP upload becomes a finished sync job: the Flask factory,
the route surface, the in-process job model, the desktop bootstrap, and the Celery path that
still exists for the cloud deployment.

Grounded in:

- [../../app.py](../../app.py) — WSGI entry point
- [../../desktop_launcher.py](../../desktop_launcher.py) — desktop entry point
- [../../synccut/paths.py](../../synccut/paths.py) — path resolution
- [../../synccut/config.py](../../synccut/config.py) — thresholds
- [../../synccut/api/factory.py](../../synccut/api/factory.py) — app factory
- [../../synccut/api/routes.py](../../synccut/api/routes.py) — API surface + jobs
- [../../synccut/api/auth.py](../../synccut/api/auth.py) — reset + Google OAuth
- [../../synccut/api/billing.py](../../synccut/api/billing.py) — Stripe
- [../../synccut/api/db.py](../../synccut/api/db.py) — persistence
- [../../synccut/api/tier_limits.py](../../synccut/api/tier_limits.py) — plan gating
- [../../synccut/workers/tasks.py](../../synccut/workers/tasks.py) — pipeline + Celery tasks
- [../../synccut/workers/celery_app.py](../../synccut/workers/celery_app.py) — Celery config
- [../../synccut/workers/job_control.py](../../synccut/workers/job_control.py) — Redis control

---

## 1. Why there are three "backends" in one repo

SyncCut has lived three lives, and all three are still present:

| Era | Shape | Still in the repo |
|---|---|---|
| Web demo | React on Vercel + Flask on Render/HF Spaces | `infra/`, `Dockerfile`, `render.yaml`, `Procfile` |
| Cloud product | Same, plus Celery + Redis + Postgres + Stripe | `workers/celery_app.py`, `job_control.py`, `billing.py` |
| Desktop product | PyInstaller `--onedir` + PyWebView + local Flask | `desktop_launcher.py`, `build.spec`, `AppxManifest.xml` |

The key architectural fact of this repo: **the desktop build disables Celery entirely and
runs the pipeline in a daemon thread inside the Flask process.**

That switch lives in [tasks.py](../../synccut/workers/tasks.py):

```python
def _desktop_build() -> bool:
    return is_frozen() or os.environ.get("SYNCCUT_DESKTOP", "").strip().lower() in {"1","true","yes"}

if _desktop_build():
    celery_app = None
    Ignore = Exception
    def _celery_task(*args, **kwargs):
        def decorator(fn): return fn         # no-op: functions stay plain callables
        return decorator
else:
    from synccut.workers.celery_app import celery_app
    _celery_task = celery_app.task
```

This is why the same `run_sync_task()` / `run_ai_cut_task()` functions can be called either
by a Celery worker or by a plain thread. **One pipeline, two schedulers.**

---

## 2. Entry points

### 2.1 `app.py` — the web/WSGI entry point

```python
load_dotenv()
app = create_app()

if __name__ == "__main__":
    port = find_free_port(5000)
    ...open browser at http://127.0.0.1:{port}/app
    app.run(host="127.0.0.1", port=port, debug=True, use_reloader=False)
```

Used by `python app.py`, by `gunicorn "synccut.api.factory:create_app()"`, and by the Heroku
`infra/Procfile` (`web: python app.py`).

### 2.2 `desktop_launcher.py` — what actually runs in the Store build

This is the `build.spec` entry point. Its `main()` sequence is the desktop lifecycle:

1. `sanitize_stdio()` — `console=False` means `sys.stdout` can be `None`; a `SafeNullWriter`
   is substituted so any stray `print()` does not crash the app.
2. `install_global_exception_hooks()` — sets `sys.excepthook` and `threading.excepthook`.
3. `normalize_environment_and_cwd()` — `os.chdir(exe_dir)`, pushes `exe_dir` and
   `exe_dir/_internal` onto `sys.path`, creates `%LOCALAPPDATA%\SyncCutStudio\tmp` and points
   `TMPDIR`/`TEMP`/`TMP` at it, and sets `SYNCCUT_DESKTOP=1`.
4. `load_bundled_env(exe_dir)` — loads `.env` from `_MEIPASS`, then `_internal`, then exe dir.
5. `ensure_webview2_runtime()` — reads four registry locations for the Edge WebView2 runtime
   (`{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}` under `EdgeUpdate\Clients`). If missing, a native
   MessageBox opens `https://go.microsoft.com/fwlink/p/?LinkId=2124703` and startup aborts.
6. Starts Flask on a **daemon thread** named `SyncCutFlaskBackend`.
7. Waits up to `BIND_TIMEOUT_SEC = 60 s` for the port to appear.
8. Polls `http://127.0.0.1:{port}/api/health` for up to `HEALTH_TIMEOUT_SEC = 60 s`
   (0.3 s between attempts, 1.5 s per request).
9. `webview.create_window(title="SyncCut Studio", width=1440, height=900,
   min_size=(1024,768), background_color="#0a0a0c")` then
   `webview.start(gui="edgechromium")`.

Logging goes to `%LOCALAPPDATA%\SyncCutStudio\startup.log` through a `RotatingFileHandler`
(3 MB × 3), logger name `synccut.desktop`.

**The port detail that matters.** `find_free_port(PREFERRED_PORT=5000)` tries 5000 first and,
if busy, binds port 0 and returns whatever the OS assigns. The launcher tells the webview the
**real** origin. Any frontend code that hardcodes `127.0.0.1:5000` will talk to the wrong
process. That is exactly the bug that `src/lib/api.ts` was corrected for (see
[04](./04-frontend-studio-experience-and-timeline-editing.md)).

**MSIX hazard (verified, still present).** `normalize_environment_and_cwd()` chdirs into the
executable's directory. Under MSIX that directory is `C:\Program Files\WindowsApps\...`,
which is **read-only**. The chdir itself is wrapped in `try/except`, but the CWD is left
there. This matters because the vendored S3FD detector in
`light_asd_repo/model/faceDetector/s3fd/__init__.py` uses
`os.path.join(os.getcwd(), PATH_WEIGHT)` to look for its weights.

---

## 3. Path resolution — `synccut/paths.py`

Everything that touches the filesystem goes through here, because MSIX makes the install
directory read-only while the user data directory stays writable.

| Function | Returns |
|---|---|
| `is_frozen()` | `bool(getattr(sys, "frozen", False))` |
| `get_exe_dir()` | frozen: `Path(sys.executable).parent`; dev: repo root |
| `get_base_dir()` | `sys._MEIPASS` -> `exe_dir/_internal` -> `exe_dir` (frozen); repo root (dev) |
| `get_user_data_dir()` | `%LOCALAPPDATA%/SyncCutStudio` (mkdir'd) |
| `get_db_file_path()` | `get_user_data_dir()/synccut.db` |
| `get_sessions_dir()` | `.../sessions` (mkdir'd) |
| `get_audio_cache_dir()` | `.../audio_cache` (mkdir'd) |
| `get_results_dir()` | `.../results` (mkdir'd) |
| `get_temp_dir()` | `.../tmp` (mkdir'd) |
| `get_frontend_dist_dir()` | first candidate containing `index.html` |
| `get_templates_dir()` | first existing templates dir |
| `resolve_binary(name)` | `ffmpeg_bin/` -> `_internal/ffmpeg_bin/` -> `bin/` -> `shutil.which()` -> bare name |
| `get_ffmpeg_path()` / `get_ffprobe_path()` | `resolve_binary("ffmpeg"/"ffprobe")` |
| `cleanup_old_temp_files(max_age_hours=24.0)` | deletes stale cache/session/temp entries |

At import time it also sets `tempfile.tempdir` and `TMPDIR`/`TEMP`/`TMP`, so **even third-party
libraries write to AppData instead of the read-only install folder.**

**Design rule that follows from this:** the package directory is *read-only code*; AppData is
*read-write state*. Every write path in the app must go through a `get_*_dir()` helper.

**Known defect:** `routes.py` calls `get_storage_info()` for `GET /api/system/storage`, but
that function no longer exists in `paths.py`. That endpoint will raise. It is listed again in
[06](./06-engineering-trade-offs-and-production-readiness.md).

---

## 4. Configuration — `synccut/config.py`

One file holds every tunable so behaviour is auditable:

```python
TARGET_SR = 16000
MAX_TAU_SEC = 30.0
DEFAULT_SYNC_MODE = "global"
ROBUST_LOSS = "soft_l1"
RANSAC_ENABLE = True
RANSAC_THRESHOLD_SEC = 0.05
CONFIDENCE_GREEN_THRESHOLD = 0.80
CONFIDENCE_YELLOW_THRESHOLD = 0.40
SYNC_LOCKED_PSR = 8.0 / SYNC_VERIFY_PSR = 3.0
SYNC_LOCKED_WINDOW_STD_MS = 2.0 / SYNC_VERIFY_WINDOW_STD_MS = 12.0
SYNC_LOCKED_LOOP_ERROR_MS = 2.0 / SYNC_VERIFY_LOOP_ERROR_MS = 15.0
SYNC_MASTER_TIE_MARGIN = 0.01
SYNC_WAVEFORM_RATE = 100
DEFAULT_DRIFT_WINDOW_SEC = 30.0
DRIFT_CORRECT_THRESHOLD_MS_PER_HR = 50.0
MIN_AUDIO_ENERGY_DB = -60.0
CLIPPING_THRESHOLD_RATIO = 0.05
MAX_SILENCE_RATIO = 0.95
MIN_SHOT_DURATION_SEC = 1.5
SWITCH_WINDOW_SEC = 0.5
TASK_SOFT_TIME_LIMIT = int(os.environ.get("SYNC_TASK_SOFT_TIME_LIMIT", "14400"))
TASK_TIME_LIMIT      = int(os.environ.get("SYNC_TASK_TIME_LIMIT", "15000"))
```

---

## 5. The app factory — `synccut/api/factory.py`

`create_app(config: dict | None = None) -> Flask`

Order of operations (this order is the contract):

1. Resolve folders — `dist_dir = get_frontend_dist_dir()`, `template_dir = get_templates_dir()`
   (falling back to `dist_dir`), then
   `Flask(__name__, template_folder=..., static_folder=str(dist_dir), static_url_path="/assets-static")`.
2. `load_runtime_env()` — read `.env` from the bundle.
3. `_configure_backend_logging()` — a `RotatingFileHandler` (5 MB × 3) on the `synccut`
   logger writing `%LOCALAPPDATA%\SyncCutStudio\backend_error.log`, `propagate=False`.
4. Set config:

   | Key | Value |
   |---|---|
   | `MAX_CONTENT_LENGTH` | `4 * 1024**3` (4 GB) |
   | `SECRET_KEY` | `_get_secret_key()` |
   | `APP_ROOT` | `str(get_base_dir())` |
   | `UPLOAD_ROOT` | `str(get_sessions_dir())` |
   | `FRONTEND_DIST` | `str(dist_dir)` |
   | `STUDIO_URL` | `SYNCCUT_STUDIO_URL` or `http://localhost:5173` |
   | `SESSION_COOKIE_SAMESITE` / `_SECURE` / `_HTTPONLY` | `Lax` / `False` / `True` |

   `_get_secret_key()` uses `SYNCCUT_SECRET_KEY` if set, otherwise reads/creates
   `%LOCALAPPDATA%\SyncCutStudio\.flask_secret_key` (`secrets.token_hex(32)`). Persisting the
   key is what keeps desktop sessions alive across restarts.
5. Register blueprints — `api_bp` (no prefix) and `billing_bp` (`/api/billing`).
6. CORS:

   ```python
   CORS(app, resources={r"/api/*": {
       "origins": "*", "supports_credentials": True,
       "methods": ["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
       "allow_headers": ["Content-Type","Authorization"]}})
   ```

   The comment in the source explains exactly why `origins: "*"`: PyWebView picks a random
   port, so a fixed allow-list of localhost ports silently blocks every real call.
7. Global error handler:

   ```python
   @app.errorhandler(Exception)
   def handle_unexpected_error(error):
       if isinstance(error, HTTPException):
           return error                        # let 404/403/413 keep their real status
       request_id = secrets.token_hex(8)
       app.logger.exception("Unhandled API exception request_id=%s method=%s path=%s", ...)
       return jsonify({"error": "Internal server error.", "request_id": request_id}), 500
   ```

   **This is the single most valuable debugging feature in the backend.** A 500 no longer
   returns Flask's HTML page; it returns a JSON body containing a `request_id` that appears
   in `backend_error.log` next to the full traceback.
8. `cleanup_old_temp_files(24.0)` — housekeeping on every boot.
9. `init_db()` unless `TESTING` is set.

Two routes live in the factory rather than the blueprint:

- `GET /api/health` -> `{"status": "ok", "frontend_present": bool, "dist_dir": str}`
- `GET /` and `GET /<path:path>` -> `serve_react()`, which serves the built SPA from
  `dist_dir` and falls back to `index.html` so `HashRouter` deep links keep working.

---

## 6. Routes and the in-process job model — `synccut/api/routes.py`

### 6.1 The three module-level registries

```python
SESSIONS: dict = {}             # session_id -> session state (last_switches, segments, ...)
LOCAL_JOBS: dict = {}           # job_id -> {"status", "metadata", "result"}
LOCAL_CANCEL_EVENTS: dict = {}  # job_id -> threading.Event
```

These are **per-process, in-memory**. That is deliberate for the desktop app (one user, one
process) and is exactly why the Dockerfiles pin `--workers 1` — with multiple gunicorn
workers, an upload would land on one worker and the status poll on another, and the job would
appear to vanish.

### 6.2 Job lifecycle

- Job id format: `f"pipeline-{uuid.uuid4().hex[:12]}"`
- Statuses: `PENDING` -> `PROGRESS` -> `SUCCESS` | `FAILURE` | `REVOKED`, plus computed
  `STALLED`, and `UNKNOWN` for an untracked id.
- Progress writes go through `_store_local_progress(job_id, current, total, status)`, which
  updates `metadata.changed_at` **only when the payload actually changed**. That is what makes
  stall detection meaningful.
- Stall detection in `job_status`:

  ```python
  if status == "PROGRESS" and time.time() - float(metadata.get("changed_at", now)) > 90:
      status = "STALLED"
  ```

  `changed_at` is stripped from the response so internal timing never leaks to the client.

- Cancellation: `POST /api/job/cancel` sets the `threading.Event`; the pipeline checks
  `cancel_check()` between work units and finishes as `REVOKED`.

### 6.3 The upload route, in order

`POST /api/upload` (`@require_auth`):

1. Validate `session_id` against `^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$` — blocks traversal.
2. Require **2–8** files; extension allow-list `ALLOWED_MEDIA_EXTENSIONS`.
3. Verify/claim ownership via `.owner.json`; 403 on a foreign session.
4. Stage into `TemporaryDirectory(prefix=".upload-", dir=sdir)` so a failed upload never
   corrupts existing media.
5. Reject any 0-byte file.
6. Build `media_paths`, then **`enforce_limits(user["id"], media_paths)`** — tier quota check
   (camera count + total duration) that raises `PermissionError` -> HTTP 403.
7. Commit with a backup (`os.replace` old aside, move new in, roll back on `OSError`).
8. Start the worker:

   ```python
   job_id = f"pipeline-{uuid.uuid4().hex[:12]}"
   LOCAL_JOBS[job_id] = {"status": "PENDING"}
   LOCAL_CANCEL_EVENTS[job_id] = threading.Event()
   app = current_app._get_current_object()      # capture the real app for the thread

   def _worker_wrapper():
       with app.app_context():
           _run_local_full_pipeline_job(job_id, session_id, saved_paths)

   threading.Thread(target=_worker_wrapper, daemon=True).start()
   return jsonify({"message": "Pipeline initiated locally", "job_id": job_id,
                   "file_count": len(saved_paths)}), 202
   ```

   Two details worth internalising: `_get_current_object()` because a thread has no Flask
   request context, and `daemon=True` so a hung job never blocks app shutdown.

9. If `Thread.start()` itself raises `RuntimeError`, the job registry entries are cleaned up
   and a 500 is returned — the job never becomes a ghost.

### 6.4 The pipeline the worker runs

`_run_local_full_pipeline_job()` calls, in order:

1. `run_sync_task(session_id, {}, file_paths[0], file_paths[1:], progress_callback=..., cancel_check=...)`
2. `run_ai_cut_task(session_id, file_paths, ...)`

and stores a `SUCCESS` result containing `status`, `session_id`, `sync_data`, `rows`,
`cameras`, `master_source`, `loop_error_s`, `segments`, `master_audio_url`.

On failure it distinguishes user cancellation from a real fault:

```python
except Exception as e:
    if cancel_event.is_set():
        ... LOCAL_JOBS[job_id] = {"status": "REVOKED", ...}
    else:
        logger.exception("Local pipeline failed job_id=%s session_id=%s", job_id, session_id)
        LOCAL_JOBS[job_id] = {"status": "FAILURE",
                              "metadata": {"status": f"Pipeline error: {str(e)}"}}
```

The `logger.exception` is what puts the traceback into `backend_error.log` — the direct fix
for "the app fails silently with 500 and I cannot see why."

### 6.5 Full route surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/health` | – | liveness + frontend presence |
| POST | `/api/session` | – | new session id |
| GET | `/api/job/status?job_id=` | – | poll one job |
| POST | `/api/job/cancel` | – | request cancellation |
| POST | `/api/upload` | yes | 2–8 files -> job |
| GET | `/api/session/<id>/master_audio` | yes | the mixdown WAV |
| GET | `/api/session/<id>/waveform/<i>` | yes | 100 Hz peak envelope, `X-Waveform-Rate: 100` |
| GET | `/api/session/<id>/media/<i>` | yes | stream a source clip |
| GET | `/api/session/<id>/thumbnail/<i>?time=` | yes | JPEG frame, `time` snapped to 10 s |
| GET/PUT | `/api/session/<id>/project` | yes | load/save the project JSON |
| GET | `/api/report/download?session_id=` | – | `sync_report.json` |
| POST | `/api/preflight` | – | media diagnostics |
| POST | `/api/review` | – | apply manual offsets |
| GET | `/api/report/csv?session_id=` | – | CSV report |
| POST | `/api/export/timeline` | yes | FCPXML/EDL/AAF/PDF |
| POST | `/api/switches` | yes | run the AI rough cut on demand |
| POST | `/api/project/<pid>/patch` | – | patch cut overrides into the manifest |
| POST | `/api/export/switch-timeline` | yes | FCPXML of the rough cut |
| POST | `/api/auth/register` \| `/login` \| `/logout` | – | email auth |
| POST/GET | `/api/auth/forgot-password` \| `/reset-password` \| `/google/start` \| `/google/poll` | – | recovery + OAuth |
| GET | `/api/auth/me` | token | current user |
| GET/POST | `/api/projects` | yes | list/create projects |
| DELETE/PATCH | `/api/projects/<pid>` | yes | delete/update |
| GET | `/api/billing/subscription` \| POST `/checkout` \| POST `/webhook` | mixed | Stripe |
| GET | `/api/system/storage` | – | **broken** (missing `get_storage_info`) |

### 6.6 Auth model

`require_auth` resolves the user from, in order:

1. `Authorization: Bearer <token>`
2. `?token=` query parameter (needed because `<video src>` cannot set headers)
3. `session["auth_token"]` cookie

If none resolve, it returns `401 {"error": "Authentication required."}` and sets
`g.current_user` on success. The query-parameter path is why media URLs are built as
`/api/session/<id>/media/<i>?token=<jwt>` in the frontend.

---

## 7. Auth flows — `synccut/api/auth.py`

### 7.1 Password reset (SMTP)

- Token: `secrets.token_urlsafe(32)`, stored **hashed** (SHA-256) in `password_reset_tokens`,
  expiring after **30 minutes**.
- Reset link base: `SYNCCUT_RESET_URL` (default `http://127.0.0.1:5000/#/reset-password`).
- **Desktop mode (no SMTP configured):** the response includes the reset token directly so a
  single-user local app can still recover an account. Verified by
  `test_password_reset_reports_missing_smtp_configuration`.
- **Email mode:** sends via SMTP and returns a generic 202, so an attacker cannot enumerate
  which emails exist. Config: `SMTP_HOST`, `SMTP_FROM`, `SMTP_PORT=587`, `SMTP_USERNAME`,
  `SMTP_PASSWORD`, `SMTP_USE_SSL`, 15 s timeout.

### 7.2 Google OAuth with PKCE

- `POST /api/auth/google/start` -> creates `flow_id`, `state`, and a PKCE `verifier`
  (challenge = base64url(SHA-256(verifier))), spins a local HTTP server on `127.0.0.1:0`, and
  opens the system browser with scope `openid email profile`.
- Flow TTL **180 s**, max **5** concurrent flows, guarded by a lock.
- The callback validates `state`, exchanges the code at `https://oauth2.googleapis.com/token`,
  verifies the ID token, and requires `email_verified`, `sub`, and `email`.
- `GET /api/auth/google/poll?flow_id=` returns `pending` (202) / `complete` (200) / `error`.
- Requires `GOOGLE_CLIENT_ID`; without it the endpoint returns 503 with a clear message.
- `db.authenticate_google_user(sub, email, name)` links an existing local account by email;
  it returns `None` if that email is already bound to a different `google_sub`.

---

## 8. Billing — `synccut/api/billing.py`

Blueprint `billing_bp` at `/api/billing`.

- `GET /subscription` -> `{tier, expires_at}`
- `POST /checkout` -> Stripe Checkout in `subscription` mode; 503 if `STRIPE_SECRET_KEY` or
  `STRIPE_PRO_PRICE_ID` is unset; 409 if already `pro`/`studio`.
  Success URL `{STUDIO_URL}/dashboard?billing=success&session_id=...`, cancel
  `{STUDIO_URL}/pricing?billing=cancelled`.
- `POST /webhook` -> verifies the Stripe signature, then:
  - `checkout.session.completed` -> re-fetch the subscription, confirm `active`/`trialing`,
    then `activate_pro_subscription(...)`
  - `customer.subscription.deleted` -> `downgrade_subscription(...)`

The re-fetch before activation is the important detail: a webhook fires on session
completion, but a subscription can complete unpaid; only a live status grants the tier.

---

## 9. Tier limits — `synccut/api/tier_limits.py` and `core/quota.py`

Two mechanisms exist:

**`core/quota.py`** holds the data and the enforcement used by the upload path:

| Limit | free | pro | studio |
|---|---|---|---|
| `max_cameras` | 2 | 8 | 8 |
| `max_duration_seconds` | 600 | 3600 | 3600 |
| `max_export_height` | 720 | 2160 | 2160 |
| `full_ai_cuts` | False | True | True |

- `check_video_duration(path)` -> seconds, via
  `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1`
- `enforce_limits(user_id, files)` raises `PermissionError` with a human message
  ("... 2 cameras", "... 10 minutes").

**`api/tier_limits.py`** defines a `check_tier_limits(feature)` decorator for `upload`,
`ai_cuts`, `export` (including format and resolution gating). Note: routes currently enforce
limits through `enforce_limits()` in the upload handler rather than the decorator — the
decorator is available but not wired to the main routes.

---

## 10. Celery path (cloud only)

- `celery_app.py` — app name `synccut_worker`, broker/backend from `CELERY_BROKER_URL` /
  `CELERY_RESULT_BACKEND` / `REDIS_URL` (default `redis://localhost:6379/0`), JSON
  serialization, UTC, `task_track_started`, soft/hard limits from `config.py` (4 h / ~4.17 h).
- `job_control.py` — Redis keys `synccut:cancel:{job_id}` and `synccut:last-progress:{job_id}`
  with a 24 h TTL; `check_cancelled()` raises `JobCancelled`, `record_progress()` preserves
  `changed_at` when nothing changed (same stall trick as the desktop path).
- `full_pipeline_task` is the Celery entry point; its docstring states it is **unused in the
  Store/desktop build**.

`docker-compose.yml` (Redis + api + worker) and `render.yaml` (web + worker + keyvalue +
postgres) are the cloud shapes. The `Dockerfile` pins `--workers 1 --threads 4` precisely
because `SESSIONS` is in-memory.

---

## 11. End-to-end sequence (desktop)

```
React                Flask (thread 1)                 Worker (thread 2)
-----                ----------------                  -----------------
POST /api/upload --> validate, stage, quota
                     commit files
                     LOCAL_JOBS[job]=PENDING
                     start thread ------------------->  run_sync_task()
202 {job_id}                                                decode 16kHz (@30%)
   |                                                        sync + master_mix (@60%)
   |                                                        write sync_report.json
   |                                                     run_ai_cut_task()
   |                                                        AI rough cut (@90%)
   |                                                        write switches.json
GET /api/job/status -- read LOCAL_JOBS --------------------- SUCCESS (@100%)
   |  (1 s interval; STALLED after 90 s idle)
   v
render program, unlock timeline
```

---

## 12. Check your understanding

1. Why does the desktop build replace Celery with a daemon thread, and what breaks if you run
   the cloud deployment with `--workers 4`?
2. `find_free_port(5000)` returns 5007. What must the frontend do to reach the backend, and
   what goes wrong if it does not?
3. Where is `changed_at` written, why is it stripped from the API response, and what feature
   depends on it?
4. A user cancels mid-sync. Trace the code path that ends in `REVOKED` rather than `FAILURE`.
5. Why is the reset token stored hashed but returned in plaintext in desktop mode?
