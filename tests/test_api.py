"""Smoke tests for the headless FastAPI app: route contract + import safety."""

from __future__ import annotations


def test_app_imports() -> None:
    from dh.api import app

    assert app.title == "Domain Hunter API"


def test_routes_registered() -> None:
    from dh.api import app

    paths = set(app.openapi()["paths"])
    assert "/health" in paths
    assert "/api/candidates" in paths
    assert "/api/candidates/{domain}" in paths
    assert "/api/opportunities" in paths
    assert "/api/pipeline/status" in paths
    assert "/api/decisions" in paths
    assert "/api/scoring-weights" in paths
    assert "/api/digest/today" in paths
    assert "/api/events" not in paths
    assert "/api/v1/today" in paths
    assert "/api/v1/candidates" in paths
    assert "/api/v1/candidates/{candidate_id}" in paths
    assert "/api/v1/candidates/{candidate_id}/reviews" in paths
    assert "/api/v1/events" in paths
    assert "/api/v1/events/{event_id}/read" in paths
    assert "/api/v1/jobs" in paths
    assert "/api/v1/jobs/{job_id}" in paths
    assert "/api/v1/config/versions" in paths
    assert "/api/v1/config/versions/{version}/activate" in paths


def test_v1_has_no_purchase_or_arbitrary_command_route() -> None:
    from dh.api import app

    paths = " ".join(app.openapi()["paths"]).lower()
    for forbidden in ("purchase", "buy", "bid", "backorder", "shell", "command", "docker"):
        assert forbidden not in paths


def test_decision_contract_rejects_unknown_actions() -> None:
    import pytest
    from pydantic import ValidationError

    from dh.api.schemas import DecisionCreate

    with pytest.raises(ValidationError):
        DecisionCreate.model_validate({"domain": "example.com", "decision": "buy_now"})
