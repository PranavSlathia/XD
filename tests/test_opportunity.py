from __future__ import annotations

from dh.opportunity import AssessmentInput, assess, name_quality_score


def test_acquisition_backed_authority_candidate_enters_research_queue() -> None:
    result = assess(
        AssessmentInput(
            domain="financebrokerage.com",
            open_pagerank=4.74,
            referring_domains=206,
            authority_rank=123_456,
            minimum_price_micros=59_000_000,
            has_deadline=True,
            market_sale_count_floor=10,
            market_average_price_floor=1170.60,
            market_terms=("finance", "brokerage"),
        )
    )
    assert result.verdict == "research"
    assert result.authority_score > 45
    assert result.confidence_score == 70
    assert "trademark clearance" in result.missing_evidence
    assert "operator maximum bid" in result.missing_evidence


def test_famous_mark_collision_is_hard_rejected() -> None:
    result = assess(
        AssessmentInput(
            domain="googleinsights.com",
            open_pagerank=8.0,
            referring_domains=50_000,
            authority_rank=100,
            minimum_price_micros=59_000_000,
            has_deadline=True,
        )
    )
    assert result.verdict == "reject"
    assert result.risk_score == 100
    assert result.rejection_reasons == ("famous-mark collision: google",)


def test_namebio_demand_strengthens_resale_evidence_without_claiming_comps() -> None:
    result = assess(
        AssessmentInput(
            domain="financebrokerage.com",
            open_pagerank=4.74,
            referring_domains=206,
            authority_rank=123_456,
            minimum_price_micros=59_000_000,
            has_deadline=True,
            market_sale_count_floor=10,
            market_average_price_floor=1170.60,
            market_terms=("finance", "brokerage"),
        )
    )
    assert result.verdict == "research"
    assert result.confidence_score == 70
    assert "keyword retail-sales demand" not in result.missing_evidence
    assert "domain-specific comparable sales" in result.missing_evidence
    assert result.signals["market_attribution"] == "NameBio.com"


def test_authority_plateau_cannot_enter_research_without_backlink_review() -> None:
    result = assess(
        AssessmentInput(
            domain="plausiblename.com",
            open_pagerank=6.55,
            referring_domains=7187,
            authority_rank=69_000,
            minimum_price_micros=59_000_000,
            has_deadline=True,
            market_sale_count_floor=50,
            market_average_price_floor=2500,
            market_terms=("plausible", "name"),
            authority_cohort_size=12,
        )
    )
    assert result.verdict == "observe"
    assert result.risk_score == 60
    assert result.signals["authority_cohort_anomaly"] is True


def test_authority_alone_is_observe_not_research() -> None:
    result = assess(
        AssessmentInput(
            domain="ruiyecs.com",
            open_pagerank=7.52,
            referring_domains=23_463,
            authority_rank=16_423,
            minimum_price_micros=59_000_000,
            has_deadline=True,
        )
    )
    assert result.verdict == "observe"
    assert "keyword retail-sales demand" in result.missing_evidence


def test_name_quality_penalizes_unpronounceable_string() -> None:
    assert name_quality_score("brightmarket") > name_quality_score("xqztrrrk")
