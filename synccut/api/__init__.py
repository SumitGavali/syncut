"""HTTP API layer (Flask today; FastAPI-ready boundary)."""

from synccut.api.factory import create_app

__all__ = [
    "create_app",
]
