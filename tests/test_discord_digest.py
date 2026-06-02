"""Unit tests for the Discord digest payload builder."""
from __future__ import annotations

from dh.api.schemas import CandidateDigestItem
from dh.notifications.discord import build_digest_payload


def test_empty_digest_renders_placeholder() -> None:
    payload = build_digest_payload([])
    assert payload["username"] == "Domain Hunter"
    assert len(payload["embeds"]) == 1
    assert "empty" in payload["embeds"][0]["title"].lower()


def test_digest_renders_each_candidate() -> None:
    candidates = [
        CandidateDigestItem(
            domain="foo.com",
            composite_score=82.5,
            current_status="available",
            quote_price_micros=11_000_000,
            top_reasons=["high authority", "clean wayback"],
        ),
        CandidateDigestItem(
            domain="bar.io",
            composite_score=75.0,
            current_status="pending_delete",
        ),
    ]
    payload = build_digest_payload(candidates)
    assert len(payload["embeds"]) == 2
    titles = [e["title"] for e in payload["embeds"]]
    assert titles == ["foo.com", "bar.io"]
    # Price formatting included for first
    assert "$11" in payload["embeds"][0]["description"]


def test_digest_truncates_to_ten() -> None:
    candidates = [
        CandidateDigestItem(domain=f"c{i}.com", composite_score=70.0, current_status="available")
        for i in range(15)
    ]
    payload = build_digest_payload(candidates)
    assert len(payload["embeds"]) == 10
