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


def test_availability_score_is_deadness_aware() -> None:
    # OPR above the floor so the low_authority filter doesn't short-circuit
    # us out before components are computed.
    dead = compute(
        EnrichmentInputs(
            current_status="available",
            availability_confidence="authoritative",
            open_pagerank=5.0,
        )
    )
    assert dead.components["availability_score"] == 100.0
    # Never authoritatively checked → 0 (cannot be confirmed acquirable).
    assert compute(EnrichmentInputs()).components["availability_score"] == 0.0
    # NXDOMAIN-style hint without authoritative confirmation → partial credit.
    # (low_authority filter doesn't fire — confidence isn't 'authoritative'.)
    hint = compute(EnrichmentInputs(current_status="available"))
    assert hint.components["availability_score"] == 35.0


def test_available_domain_outranks_live_megadomain() -> None:
    """Regression guard for lesson #1 at the scoring layer.

    A live mega-domain (e.g. github.com) is never availability-checked, so it
    must NOT outrank a genuinely available domain — even one with maximal
    authority on the citing side. The available domain needs OPR above the
    authority floor to clear the low_authority hard filter.
    """
    live_megadomain = compute(
        EnrichmentInputs(max_source_authority=10_000_000, distinct_sources=50)
    )
    available_with_authority = compute(
        EnrichmentInputs(
            max_source_authority=2_000,
            distinct_sources=2,
            open_pagerank=5.0,  # above floor
            current_status="available",
            availability_confidence="authoritative",
        )
    )
    assert not live_megadomain.hard_filtered
    assert not available_with_authority.hard_filtered
    assert available_with_authority.composite > live_megadomain.composite


def test_low_authority_available_is_hard_filtered() -> None:
    """An available domain with OPR below the floor is rejected.

    Encodes the dofollow-authority requirement: availability alone is worthless;
    we want real backlink authority. reactnativemodules.com (real ingest data:
    OPR 1.08, available) is the motivating case.
    """
    out = compute(
        EnrichmentInputs(
            current_status="available",
            availability_confidence="authoritative",
            open_pagerank=1.08,  # the real reactnativemodules.com value
            min_opr_authority=3.0,
        )
    )
    assert out.hard_filtered
    assert out.hard_filter_reason == "low_authority"


def test_high_authority_available_passes_floor() -> None:
    out = compute(
        EnrichmentInputs(
            current_status="available",
            availability_confidence="authoritative",
            open_pagerank=7.0,
            min_opr_authority=3.0,
        )
    )
    assert not out.hard_filtered
    assert out.composite > 0


def test_low_authority_filter_does_not_misfire_on_live_domain() -> None:
    """Live/unchecked domains have OPR ~0 too. They must NOT be tagged
    'low_authority' (that reason should only apply to confirmed-available
    domains). They just score low naturally via availability_score=0."""
    out = compute(
        EnrichmentInputs(
            max_source_authority=10_000_000,
            distinct_sources=20,
            open_pagerank=0.0,  # never checked
            # no current_status, no availability_confidence
        )
    )
    assert not out.hard_filtered  # filter must not misfire
