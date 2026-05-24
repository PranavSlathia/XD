"""Composite-score computation (PRD §4.5).

Given a candidate's joined enrichments, produce a composite 0-100 score using
the weights stored in ``scoring_weights`` for the requested version. Pure
function — no IO, easy to unit-test.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dh.score import normalize as N

HardFilterReason = Literal[
    "tm_risk",
    "spam_history",
    "not_available",
    "low_authority",
    "reputation_flag",
    "premium_quote",
]


@dataclass(frozen=True)
class EnrichmentInputs:
    """All raw inputs to the composite formula. Missing = 0/None."""

    max_source_authority: float = 0.0      # max stars/citations/forward-cites
    distinct_sources: int = 0
    referring_domains: int = 0
    open_pagerank: float = 0.0             # 0-10
    wayback_classification: str | None = None  # 'clean'|'mixed'|'spam_history'|...
    wayback_first_capture_year: int | None = None
    current_year: int = 2026
    spam_flag: bool = False
    tm_risk_probability: float = 0.0       # 0-1
    reputation_flag: Literal["malicious", "mixed", "clean", None] = None
    quote_price_micros: int | None = None
    premium_ceiling_micros: int = 200_000_000
    current_status: str | None = None
    availability_confidence: str | None = None
    # Authority floor for digest-eligibility. Only applies when a domain is
    # confirmed available — see the low_authority hard filter.
    min_opr_authority: float = 3.0


@dataclass(frozen=True)
class ScoreBreakdown:
    composite: float
    hard_filtered: bool
    hard_filter_reason: HardFilterReason | None
    components: dict[str, float]


# Default weights mirror scoring_weights v3 (authority-first). Positive weights
# sum to 1.0. v3 reflects the dofollow-authority requirement: GitHub README
# links are rel="nofollow ugc" so max_source_authority is mostly noise and
# is heavily demoted (0.05). open_pagerank dominates (0.45) because PageRank
# flows only through followed links — nofollow-only domains naturally score 0.
# availability_score is a smaller additive (0.15) because the digest already
# hard-gates on availability_confidence; it doesn't need to dominate the score.
DEFAULT_WEIGHTS: dict[str, float] = {
    "availability_score": 0.15,
    "max_source_authority": 0.05,
    "source_diversity_bonus": 0.05,
    "referring_domains_score": 0.10,
    "open_pagerank_score": 0.45,
    "wayback_clean_score": 0.10,
    "age_score": 0.10,
    "spam_penalty": -0.10,
    "tm_risk_penalty": -0.10,
    "reputation_penalty": -0.10,
}


def _availability_score(status: str | None, confidence: str | None) -> float:
    """Deadness-aware acquirability signal (0-100).

    Confirmed-available / deletion-state domains score top; a domain that is
    live or has never been authoritatively checked scores 0. This is what keeps
    live mega-domains off the top of the ranking (deadness-first, lesson #1).
    """
    s = (status or "").lower()
    if confidence == "authoritative":
        if s in {"available", "pending_delete", "redemption_period"}:
            return 100.0
        if s == "expiring_soon":
            return 60.0
        return 0.0  # authoritative + registered/other → not acquirable
    # Non-authoritative hint only (e.g. a DNS NXDOMAIN suggestion) — worth a
    # little, but not confirmed.
    if s in {"available", "pending_delete"}:
        return 35.0
    return 0.0


def _wayback_clean(cls: str | None) -> float:
    if cls == "clean":
        return 100.0
    if cls == "mixed":
        return 50.0
    return 0.0


def _reputation_penalty(flag: str | None) -> float:
    if flag == "malicious":
        return 100.0
    if flag == "mixed":
        return 50.0
    return 0.0


def compute(
    inputs: EnrichmentInputs,
    *,
    weights: dict[str, float] | None = None,
) -> ScoreBreakdown:
    """Compute the composite score + hard-filter verdict."""
    weights = weights or DEFAULT_WEIGHTS

    # Hard filters (PRD §4.5). Checked in priority order.
    if inputs.tm_risk_probability >= 1.0:
        return ScoreBreakdown(
            composite=0.0,
            hard_filtered=True,
            hard_filter_reason="tm_risk",
            components={},
        )
    if inputs.spam_flag or inputs.wayback_classification in {
        "adult_history",
        "spam_history",
        "pbn_history",
    }:
        return ScoreBreakdown(
            composite=0.0,
            hard_filtered=True,
            hard_filter_reason="spam_history",
            components={},
        )
    if inputs.reputation_flag == "malicious":
        return ScoreBreakdown(
            composite=0.0,
            hard_filtered=True,
            hard_filter_reason="reputation_flag",
            components={},
        )
    if (
        inputs.current_status == "registered"
        and inputs.availability_confidence == "authoritative"
    ):
        return ScoreBreakdown(
            composite=0.0,
            hard_filtered=True,
            hard_filter_reason="not_available",
            components={},
        )
    # Authority floor — only fires for *confirmed-available* domains that lack
    # backlink authority. Live/unchecked domains naturally score low via
    # availability_score=0; tagging them "low_authority" would be misleading.
    # Open PageRank inherently weights dofollow (PageRank doesn't flow through
    # rel=nofollow), so a domain whose only inbound links are nofollow (e.g.
    # GitHub README citations) sits near zero here — exactly the signal we want.
    if (
        inputs.availability_confidence == "authoritative"
        and (inputs.current_status or "").lower()
        in {"available", "pending_delete", "redemption_period", "expiring_soon"}
        and inputs.open_pagerank < inputs.min_opr_authority
    ):
        return ScoreBreakdown(
            composite=0.0,
            hard_filtered=True,
            hard_filter_reason="low_authority",
            components={},
        )
    if (
        inputs.quote_price_micros is not None
        and inputs.quote_price_micros >= inputs.premium_ceiling_micros
    ):
        return ScoreBreakdown(
            composite=0.0,
            hard_filtered=True,
            hard_filter_reason="premium_quote",
            components={},
        )

    age_years = 0.0
    if inputs.wayback_first_capture_year:
        age_years = max(0, inputs.current_year - inputs.wayback_first_capture_year)

    components: dict[str, float] = {
        "availability_score": _availability_score(
            inputs.current_status, inputs.availability_confidence
        ),
        "max_source_authority": N.normalize_max_source_authority(inputs.max_source_authority),
        "source_diversity_bonus": N.normalize_source_diversity(inputs.distinct_sources),
        "referring_domains_score": N.normalize_referring_domains(inputs.referring_domains),
        "open_pagerank_score": N.normalize_open_pagerank(inputs.open_pagerank),
        "wayback_clean_score": _wayback_clean(inputs.wayback_classification),
        "age_score": N.normalize_age(age_years),
        "spam_penalty": 100.0 if inputs.spam_flag else 0.0,
        "tm_risk_penalty": 100.0 * max(0.0, min(1.0, inputs.tm_risk_probability)),
        "reputation_penalty": _reputation_penalty(inputs.reputation_flag),
    }

    score = 0.0
    for k, v in components.items():
        score += weights.get(k, 0.0) * v

    composite = max(0.0, min(100.0, score))
    return ScoreBreakdown(
        composite=composite,
        hard_filtered=False,
        hard_filter_reason=None,
        components=components,
    )
