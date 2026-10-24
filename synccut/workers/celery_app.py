"""
Celery application stub — ready for Redis broker / result backend.

Activate when deploying workers:
    celery -A synccut.workers.celery_app.celery_app worker --loglevel=info
"""
from __future__ import annotations

import os

try:
    from celery import Celery
except ImportError:  # Celery optional until production queue is enabled
    Celery = None  # type: ignore


def _make_celery() -> "Celery | None":
    if Celery is None:
        return None
    broker = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    backend = os.environ.get("CELERY_RESULT_BACKEND", broker)
    app = Celery("synccut", broker=broker, backend=backend)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
    )
    return app


celery_app = _make_celery()


# Example task signature for the future Redis/Celery cutover from ThreadPoolExecutor:
# @celery_app.task(name="synccut.sync_job")
# def sync_job(session_id: str, payload: dict) -> dict:
#     ...
