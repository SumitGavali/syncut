---
title: SyncCut
emoji: 🎬
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# SyncCut — Web App

This connects your existing, unmodified core logic to a real product website.

## What's inside
- **Core logic (untouched):** `extract.py`, `sync_engine.py`, `synccut.py`,
  `camera_switch.py`, `timeline_builder.py`, `export_switch_timeline.py`
- **Backend glue:** `app.py` (Flask) — only handles uploads/sessions and calls
  straight into the core functions above, same as the old tkinter GUI did.
- **`templates/index.html`** — the public landing page (product marketing site).
- **`templates/dashboard.html`** — the actual working tool (upload → sync →
  export), unchanged from your version.
- **`static/testimonials/`** — the screenshots used as social proof on the
  landing page.

## Requirements
- Python 3.9+
- [FFmpeg](https://ffmpeg.org/download.html) installed and on your PATH
  (used by `extract.py` for audio extraction)

## Run it
```bash
cd synccut
pip install -r requirements.txt
python app.py
```
Then open **http://localhost:5000**

- `/` → the landing page (product site)
- `/app` → the working dashboard (upload files, run sync, get switches, export FCPXML)

## Windows desktop build and account setup

Build the Studio frontend before packaging the desktop app:

```powershell
Push-Location synccut-studio
npm run build
Pop-Location
pyinstaller --noconfirm --clean build.spec
```

The desktop app reads account-provider settings from the environment of the process that launches it; the build does not embed credentials:

- Set `GOOGLE_CLIENT_ID` to a Google OAuth client ID created for a **Desktop app**. Google sign-in opens the system browser and returns to SyncCut.
- For password recovery, set `SMTP_HOST`, `SMTP_PORT` (usually `587`), and `SMTP_FROM`. If the server requires authentication, also set `SMTP_USERNAME` and `SMTP_PASSWORD`. Use `SMTP_USE_SSL=true` with SSL-enabled SMTP (usually port `465`); otherwise SyncCut uses STARTTLS.
- `SYNCCUT_RESET_URL` is optional; the default reset link opens the local desktop app at `http://127.0.0.1:5000`. Keep the app running while you open and submit the reset link.

Do not commit SMTP credentials. Google sign-in and password recovery report a clear configuration error until their provider settings are present.

## Routes (unchanged behavior)
- `POST /api/session` — new session
- `POST /api/sync` — reference + inputs → sync report
- `GET  /api/report/download` — download sync_report.json
- `GET  /api/session/<session_id>/thumbnail/<index>?time=<seconds>` — authenticated, cached video frame for the editor filmstrip
- `POST /api/export/timeline` — export synced multi-track FCPXML
- `POST /api/switches` — offset-aligned camera switch suggestions
- `POST /api/export/switch-timeline` — export rough-cut FCPXML

## SaaS billing and deployment

- Copy `.env.example` to `.env`. Without `DATABASE_URL`, the API uses a local SQLite database; PostgreSQL is used when `DATABASE_URL` is set.
- Configure `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, and `STRIPE_PRO_PRICE_ID` in the server environment. Register `/api/billing/webhook` in Stripe for `checkout.session.completed` and `customer.subscription.deleted`.
- The React Studio is in `synccut-studio/`; its dashboard and `/pricing` page use Stripe Checkout for Pro upgrades.
- The root `Dockerfile` installs FFmpeg in the runtime image. `render.yaml` provisions the API, Celery worker, Redis, and PostgreSQL services.

The current Celery pipeline passes local media paths between the API and worker. Render services have isolated filesystems, so setting `SYNCCUT_DATA_DIR` to the same path does not share uploaded files. Configure a shared filesystem or move media storage to an object-storage backend before processing uploads with the Render worker.

## Note
Large uploads (multi-GB 4K footage) can take a while to process — this is
CPU-bound audio cross-correlation running locally, not a network limitation.
