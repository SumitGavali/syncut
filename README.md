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
