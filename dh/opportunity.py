"""Deterministic first-pass opportunity assessment.

This is a research prioritizer, not a valuation or buying model. It intentionally
keeps trademark review, archive-content review, comparable sales, and a human
price ceiling in ``missing_evidence`` so an automatic score can never be treated
as permission to acquire a domain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MODEL_VERSION = "market-v2"

_VOWELS = frozenset("aeiouy")
_ABUSE_TERMS = frozenset(
    {
        "adult",
        "apk",
        "casino",
        "cialis",
        "clomid",
        "crack",
        "escort",
        "gabapentin",
        "hack",
        "ivermectin",
        "pharm",
        "pharmacy",
        "pills",
        "porn",
        "slot",
        "tadalafil",
        "togel",
        "viagra",
    }
)
_FAMOUS_MARKS = frozenset(
    {
        "adidas",
        "amazon",
        "apple",
        "dior",
        "facebook",
        "google",
        "instagram",
        "microsoft",
        "netflix",
        "paypal",
        "shopify",
        "stussy",
        "tiktok",
        "twitter",
        "whatsapp",
        "youtube",
    }
)
_GENERIC_COMMERCIAL_TERMS = frozenset(
    {
        "broker",
        "brokerage",
        "business",
        "career",
        "cloud",
        "crypto",
        "design",
        "digital",
        "energy",
        "farm",
        "finance",
        "financial",
        "health",
        "homes",
        "legal",
        "loans",
        "market",
        "media",
        "money",
        "mortgage",
        "property",
        "retail",
        "shop",
        "software",
        "solar",
        "travel",
        "voice",
    }
)


@dataclass(frozen=True, slots=True)
class AssessmentInput:
    domain: str
    open_pagerank: float
    referring_domains: int
    authority_rank: int
    minimum_price_micros: int | None
    has_deadline: bool
    market_sale_count_floor: int | None = None
    market_average_price_floor: float | None = None
    market_terms: tuple[str, ...] = ()
    authority_cohort_size: int = 1
    min_market_sale_count_floor: int = 10
    research_threshold: float = 45.0


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    authority_score: float
    resale_score: float
    risk_score: float
    confidence_score: float
    overall_score: float
    verdict: str
    reasons: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    signals: dict[str, object]


def _max_consonant_run(value: str) -> int:
    longest = current = 0
    for char in value:
        if char in _VOWELS:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def name_quality_score(sld: str) -> float:
    """Cheap, language-agnostic pronounceability/length prior (0-100)."""
    length = len(sld)
    if length <= 4:
        score = 70.0
    elif length <= 8:
        score = 92.0
    elif length <= 12:
        score = 82.0
    elif length <= 15:
        score = 66.0
    else:
        score = 48.0
    vowel_ratio = sum(c in _VOWELS for c in sld) / max(1, length)
    if not 0.20 <= vowel_ratio <= 0.65:
        score -= 25.0
    consonant_run = _max_consonant_run(sld)
    if consonant_run >= 5:
        score -= min(30.0, 8.0 * (consonant_run - 4))
    if any(char * 3 in sld for char in set(sld)):
        score -= 18.0
    return max(0.0, min(100.0, score))


def _commercial_terms(sld: str) -> list[str]:
    raw = {term for term in _GENERIC_COMMERCIAL_TERMS if term in sld}
    # Keep the most specific match ("brokerage" rather than both it and
    # "broker") so one concept cannot inflate the prior twice.
    return sorted(term for term in raw if not any(term != other and term in other for other in raw))


def assess(value: AssessmentInput) -> AssessmentResult:
    sld = value.domain.rsplit(".", 1)[0].lower()
    name_score = name_quality_score(sld)
    commercial_terms = _commercial_terms(sld)
    breadth = min(1.0, math.log10(value.referring_domains + 1) / 4.0)
    authority = min(100.0, value.open_pagerank * 8.0 + breadth * 20.0)

    rejection_reasons: list[str] = []
    matched_abuse = sorted(term for term in _ABUSE_TERMS if term in sld)
    matched_marks = sorted(mark for mark in _FAMOUS_MARKS if mark in sld)
    if matched_abuse:
        rejection_reasons.append(f"high-risk/spam term: {', '.join(matched_abuse)}")
    if matched_marks:
        rejection_reasons.append(f"famous-mark collision: {', '.join(matched_marks)}")
    authority_anomaly = value.authority_cohort_size >= 5
    risk = 100.0 if rejection_reasons else (60.0 if authority_anomaly else 10.0)

    # Name and generic-term scoring is a weak fallback. NameBio's aggregated
    # retail stats are real demand evidence, but still not domain-specific comps.
    commercial_score = 0.0
    if commercial_terms:
        commercial_score = 55.0 if len(commercial_terms) == 1 else 75.0
    market_demand_score: float | None = None
    market_qualified = False
    if (
        value.market_sale_count_floor is not None
        and value.market_sale_count_floor >= value.min_market_sale_count_floor
    ):
        market_qualified = True
        average_price = max(0.0, value.market_average_price_floor or 0.0)
        market_demand_score = min(
            100.0,
            math.log10(value.market_sale_count_floor + 1) / 3.0 * 70.0
            + math.log10(average_price + 1) / 5.0 * 30.0,
        )
        resale = min(100.0, name_score * 0.35 + market_demand_score * 0.65)
    else:
        resale = min(100.0, name_score * 0.55 + commercial_score * 0.35)
    confidence = 35.0  # current authority dataset + referring-domain breadth
    if value.minimum_price_micros is not None:
        confidence += 15.0
    if value.has_deadline:
        confidence += 10.0
    if market_demand_score is not None:
        confidence += 10.0

    missing = [
        "Wayback content/history review",
        "independent backlink/profile review",
        "trademark clearance",
        "domain-specific comparable sales",
        "end-user buyer thesis",
        "operator maximum bid",
    ]
    if market_demand_score is None:
        missing.insert(2, "keyword retail-sales demand")
    reasons = [
        f"OpenPageRank {value.open_pagerank:.2f} with {value.referring_domains:,} referring domains",
        f"name-quality prior {name_score:.0f}/100",
    ]
    if commercial_terms:
        reasons.append(f"generic commercial terms: {', '.join(commercial_terms)}")
    if market_demand_score is not None:
        reasons.append(
            f"NameBio weakest relevant placement: {value.market_sale_count_floor:,} retail sales "
            f"averaging ${value.market_average_price_floor or 0:,.0f}"
        )
    elif value.market_sale_count_floor is not None:
        reasons.append(
            f"NameBio demand below gate: {value.market_sale_count_floor} weakest-placement sales "
            f"(requires {value.min_market_sale_count_floor})"
        )
    if authority_anomaly:
        reasons.append(
            f"authority anomaly: near-identical OPR/ref-domain cohort shared by "
            f"{value.authority_cohort_size} inventory domains"
        )
    if value.minimum_price_micros is not None:
        reasons.append(
            f"verified opening acquisition price ${value.minimum_price_micros / 1_000_000:.0f}"
        )
    if value.has_deadline:
        reasons.append("verified acquisition date or deadline")

    overall = max(
        0.0,
        min(
            100.0,
            0.50 * authority + 0.30 * resale + 0.20 * confidence - 0.45 * risk,
        ),
    )
    if rejection_reasons:
        verdict = "reject"
    elif authority_anomaly or market_demand_score is None:
        verdict = "observe"
    elif overall >= value.research_threshold:
        verdict = "research"
    else:
        verdict = "observe"

    return AssessmentResult(
        authority_score=round(authority, 2),
        resale_score=round(resale, 2),
        risk_score=round(risk, 2),
        confidence_score=round(confidence, 2),
        overall_score=round(overall, 2),
        verdict=verdict,
        reasons=tuple(reasons),
        rejection_reasons=tuple(rejection_reasons),
        missing_evidence=tuple(missing),
        signals={
            "name_quality": round(name_score, 2),
            "open_pagerank": value.open_pagerank,
            "referring_domains": value.referring_domains,
            "authority_rank": value.authority_rank,
            "commercial_terms": commercial_terms,
            "market_terms": list(value.market_terms),
            "market_sale_count_floor": value.market_sale_count_floor,
            "market_average_price_floor": value.market_average_price_floor,
            "market_demand_score": (
                round(market_demand_score, 2) if market_demand_score is not None else None
            ),
            "market_attribution": (
                "NameBio.com" if value.market_sale_count_floor is not None else None
            ),
            "market_demand_qualified": market_qualified,
            "minimum_market_sale_count_floor": value.min_market_sale_count_floor,
            "authority_cohort_size": value.authority_cohort_size,
            "authority_cohort_anomaly": authority_anomaly,
            "matched_abuse_terms": matched_abuse,
            "matched_famous_marks": matched_marks,
        },
    )
