import os
from celery import Celery

from synccut.config import TASK_SOFT_TIME_LIMIT, TASK_TIME_LIMIT

# WHY: We use Redis as the message broker (the queue) and the backend (to store results).
# We pull these from environment variables so it works locally AND in Docker.
broker_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

# WHY: We instantiate Celery. The name "synccut_worker" is just an identifier.
celery_app = Celery(
    "synccut_worker",
    broker=broker_url,
    backend=result_backend,
    include=["synccut.workers.tasks"] # WHY: Tells Celery where to find our actual tasks
)

# WHY: Standard Celery settings for JSON serialization (safest and most readable).
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # WHY: Prevents a task from hanging forever if the worker crashes.
    task_track_started=True,
    result_backend=result_backend,  # Force the backend to use Redis
    broker_connection_retry_on_startup=True,
    task_soft_time_limit=TASK_SOFT_TIME_LIMIT,
    task_time_limit=TASK_TIME_LIMIT,
)