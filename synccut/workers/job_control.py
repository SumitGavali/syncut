"""Redis-backed cooperative cancellation and task-progress timestamps."""
from __future__ import annotations

import json
import os
import time

from redis import Redis

from synccut.workers.celery_app import result_backend

JOB_TTL_SECONDS = 24 * 60 * 60


class JobCancelled(Exception):
    """Raised when a worker observes a cooperative cancellation request."""


def redis_client() -> Redis:
    return Redis.from_url(
        result_backend,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def cancellation_key(job_id: str) -> str:
    return f"synccut:cancel:{job_id}"


def progress_key(job_id: str) -> str:
    return f"synccut:last-progress:{job_id}"


def check_cancelled(job_id: str) -> None:
    if redis_client().exists(cancellation_key(job_id)):
        raise JobCancelled(f"Job {job_id} was cancelled.")


def record_progress(job_id: str, current, total, status: str) -> None:
    client = redis_client()
    snapshot = {"current": current, "total": total, "status": status}
    key = progress_key(job_id)
    previous_raw = client.get(key)
    previous = json.loads(previous_raw) if previous_raw else None
    if previous is None or any(previous.get(k) != snapshot[k] for k in snapshot):
        snapshot["changed_at"] = time.time()
        client.set(key, json.dumps(snapshot), ex=JOB_TTL_SECONDS)
    else:
        snapshot["changed_at"] = previous.get("changed_at")
        client.expire(key, JOB_TTL_SECONDS)


def get_last_progress(job_id: str):
    value = redis_client().get(progress_key(job_id))
    return json.loads(value) if value else None


def request_cancel(job_id: str) -> None:
    redis_client().set(cancellation_key(job_id), "1", ex=JOB_TTL_SECONDS)


def clear_partial_audio(cache_dir: str) -> None:
    if not os.path.isdir(cache_dir):
        return
    for filename in os.listdir(cache_dir):
        if filename.endswith(".part"):
            path = os.path.join(cache_dir, filename)
            if os.path.isfile(path):
                os.remove(path)
