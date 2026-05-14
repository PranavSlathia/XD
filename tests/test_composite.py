"""Unit tests for the composite-score function (PRD §4.5)."""
from __future__ import annotations

from dh.score.composite import EnrichmentInputs, compute


def test_clean_high_authority_scores_high() -> None:
    inputs = EnrichmentInputs(
        max_source_authority=50_000,
        distinct_sources=5,
        referring_domains=100,
        open_pagerank=5.0,
        wayback_classification="clean",
        wayback_first_capture_year=2010,
        current_year=2026,
        current_status="available",
        availability_confidence="authoritative",
    )
    out = compute(inputs)
    assert not out.hard_filtered
    assert out.composite > 60


def test_no_signals_scores_zero_ish() -> None:
    out = compute(EnrichmentInputs())
    assert not out.hard_filtered
    assert out.composite < 30


def test_spam_history_hard_filters() -> None:
    out = compute(EnrichmentInputs(wayback_classification="spam_history"))
    assert out.hard_filtered
    assert out.hard_filter_reason == "spam_history"


def test_registered_authoritative_hard_filters() -> None:
    out = compute(
        EnrichmentInputs(
            current_status="registered",
            availability_confidence="authoritative",
            max_source_authority=10_000,
        )
    )
    assert out.hard_filtered
    assert out.hard_filter_reason == "not_available"


def test_premium_quote_hard_filters() -> None:
    out = compute(
        EnrichmentInputs(
            quote_price_micros=500_000_000,
            premium_ceiling_micros=200_000_000,
        )
    )
    assert out.hard_filtered
    assert out.hard_filter_reason == "premium_quote"


def test_tm_risk_one_hard_filters() -> None:
    out = compute(EnrichmentInputs(tm_risk_probability=1.0))
    assert out.hard_filtered
    assert out.hard_filter_reason == "tm_risk"


def test_composite_clipped_to_zero_hundred() -> None:
    # Pathological negative inputs should still clip cleanly.
    out = compute(EnrichmentInputs(tm_risk_probability=0.99))
    assert 0.0 <= out.composite <= 100.0


def test_composite_components_populated() -> None:
    inputs = EnrichmentInputs(
        max_source_authority=10_000,
        distinct_sources=3,
        open_pagerank=4.0,
    )
    out = compute(inputs)
    assert "max_source_authority" in out.components
    assert out.components["open_pagerank_score"] == 40.0
    assert out.components["source_diversity_bonus"] == 60.0
