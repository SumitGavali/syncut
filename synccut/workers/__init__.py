"""Async workers (Celery/Redis placeholders for production job queues)."""

__all__ = [
    "get_celery_app",
]


def get_celery_app():
    """Lazy Celery app factory — wire Redis broker when deploying workers."""
    from synccut.workers.celery_app import celery_app

    return celery_app
