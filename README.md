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
- `POST /api/export/timeline` — export synced multi-track FCPXML
- `POST /api/switches` — offset-aligned camera switch suggestions
- `POST /api/export/switch-timeline` — export rough-cut FCPXML

## Note
Large uploads (multi-GB 4K footage) can take a while to process — this is
CPU-bound audio cross-correlation running locally, not a network limitation.
