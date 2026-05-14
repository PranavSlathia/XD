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


@dataclass(frozen=True)
class ScoreBreakdown:
    composite: float
    hard_filtered: bool
    hard_filter_reason: HardFilterReason | None
    components: dict[str, float]


# Default weights match the PRD §4.5 starting weights / scoring_weights v1.
DEFAULT_WEIGHTS: dict[str, float] = {
    "max_source_authority": 0.25,
    "source_diversity_bonus": 0.10,
    "referring_domains_score": 0.20,
    "open_pagerank_score": 0.15,
    "wayback_clean_score": 0.10,
    "age_score": 0.10,
    "spam_penalty": -0.10,
    "tm_risk_penalty": -0.10,
    "reputation_penalty": -0.10,
}


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
