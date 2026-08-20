"""Authority Asset screening and direct referring-page evidence summaries."""

from __future__ import annotations

from dataclasses import dataclass

MODEL_VERSION = "authority-screen-v1"


@dataclass(frozen=True, slots=True)
class AuthorityLink:
    source_domain: str
    source_url: str
    anchor_text: str | None = None
    context_text: str | None = None
    live: bool = False
    editorial: bool = False
    followable: bool = False
    relevant: bool = False
    independent: bool = True
    technical: bool = False


@dataclass(frozen=True, slots=True)
class AuthorityScreenInput:
    domain: str
    referring_domains: int | None = None
    open_pagerank: float | None = None
    observed_links: tuple[AuthorityLink, ...] = ()
    minimum_referring_domains: int = 10


@dataclass(frozen=True, slots=True)
class AuthorityScreenResult:
    domain: str
    screen_passed: bool
    score: float | None
    reasons: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    verified_independent_domains: int
    model_version: str = MODEL_VERSION


def screen_authority(value: AuthorityScreenInput) -> AuthorityScreenResult:
    valid_links = tuple(
        link
        for link in value.observed_links
        if link.live
        and link.editorial
        and link.followable
        and link.independent
        and not link.technical
    )
    independent_domains = len({link.source_domain.lower() for link in valid_links})
    provider_prefilter = (value.referring_domains or 0) >= value.minimum_referring_domains
    direct_prefilter = independent_domains > 0
    passed = provider_prefilter or direct_prefilter

    reasons: list[str] = []
    if provider_prefilter:
        reasons.append("provider referring-domain prefilter passed")
    if direct_prefilter:
        reasons.append("at least one independent editorial referring page verified")

    # This priority is strictly intra-lane and is not readiness.  Direct link
    # evidence is weighted more than provider aggregates.
    score: float | None = None
    if passed:
        score = min(
            100.0,
            35.0
            + min(30.0, (value.referring_domains or 0) ** 0.5 * 3.0)
            + min(35.0, independent_domains * 12.0),
        )

    missing: list[str] = []
    if independent_domains == 0:
        missing.append("direct referring-page validation")
    if not value.observed_links:
        missing.append("anchor, context, rel, and topical evidence")
    missing.extend(("historical topic consistency", "authority rubric calibration"))
    return AuthorityScreenResult(
        domain=value.domain,
        screen_passed=passed,
        score=round(score, 2) if score is not None else None,
        reasons=tuple(reasons),
        missing_evidence=tuple(dict.fromkeys(missing)),
        verified_independent_domains=independent_domains,
    )
