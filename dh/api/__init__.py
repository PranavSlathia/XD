"""FastAPI dashboard backend.

``app`` is exposed at the package root so uvicorn can import as ``dh.api:app``.
"""
from dh.api.main import app

__all__ = ["app"]
