"""
Root WSGI / CLI entrypoint for SyncCut.

Instantiates the Flask app via the App Factory so gunicorn, Flask CLI,
and ``python app.py`` all share the same configuration path.

Run locally:
    pip install -e .
    python app.py
Then open http://localhost:5000/app

Gunicorn (HF Spaces / Docker):
    gunicorn app:app --bind 0.0.0.0:7860 --timeout 600 --workers 1 --threads 4
"""
from __future__ import annotations

import threading
import time
import webbrowser

from synccut.api import create_app
from synccut.api.factory import find_free_port

app = create_app()


if __name__ == "__main__":
    host = "127.0.0.1"
    port = find_free_port(5000)
    url = f"http://{host}:{port}/app"
    threading.Thread(
        target=lambda: (time.sleep(1.2), webbrowser.open(url)),
        daemon=True,
    ).start()
    print(f"SyncCut Desktop running at {url}")
    app.run(host=host, port=port, debug=False)
