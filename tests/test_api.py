"""Smoke tests for the headless FastAPI app: route contract + import safety."""
from __future__ import annotations


def test_app_imports() -> None:
    from dh.api import app

    assert app.title == "Domain Hunter API"


def test_routes_registered() -> None:
    from dh.api import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/health" in paths
    assert "/api/candidates" in paths
    assert "/api/candidates/{domain}" in paths
    assert "/api/decisions" in paths
    assert "/api/scoring-weights" in paths
    assert "/api/digest/today" in paths
    assert "/api/events" not in paths
