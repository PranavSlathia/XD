"""Async DB helpers for the Discord bot.

Thin wrappers over the existing models + session factory. They return plain frozen
dataclasses (not ORM rows) so the embed builders + tests never touch a session.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any

from sqlalchemy import desc, exists, select
from sqlalchemy.orm import aliased

from dh.config import settings
from dh.db.engine import session_scope
from dh.db.models import (
    AvailabilityCheck,
    Candidate,
    MarketplaceListing,
    OpportunityAssessment,
    Outcome,
    RegistrarQuote,
    ScoringWeights,
    SourceMention,
    WaybackSnapshot,
)
from dh.opportunity import MODEL_VERSION

DIGEST_STATUSES = ("available", "pending_delete", "redemption_period", "expiring_soon")
DECISIONS = ("bought", "passed", "watching", "needs_manual_review", "lost_to_other")
TERMINAL_DECISIONS = ("passed", "bought", "lost_to_other")


@dataclasses.dataclass(frozen=True, slots=True)
class ShortlistItem:
    domain: str
    composite_score: float | None
    current_status: str | None
    quote_price_micros: int | None
    top_reasons: list[str]
    closes_at: str | None = None
    missing_evidence: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True, slots=True)
class CandidateRow:
    domain: str
    composite_score: float | None
    current_status: str | None
    availability_confidence: str | None
    open_pagerank: float | None
    hard_filtered: bool
    hard_filter_reason: str | None
    top_reasons: list[str]


@dataclasses.dataclass(frozen=True, slots=True)
class MentionRow:
    source_url: str | None
    context_type: str | None
    context_snippet: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class AvailabilityRow:
    source: str
    status: str | None
    is_authoritative: bool | None


@dataclasses.dataclass(frozen=True, slots=True)
class WaybackRow:
    first_capture: str | None
    last_capture: str | None
    capture_count: int | None


@dataclasses.dataclass(frozen=True, slots=True)
class CandidateDetail:
    candidate: CandidateRow
    mentions: list[MentionRow]
    availability: list[AvailabilityRow]
    wayback: list[WaybackRow]
    latest_quote_micros: int | None
    latest_decision: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class ConfigInfo:
    weights_version: int | None
    weights: dict[str, float]
    digest_min_score: int
    digest_max_items: int
    premium_ceiling_usd: int
    opr_min_authority: float


def _as_float(value: Any) -> float | None:
    return float(value) if value is not None else None  # Numeric -> Decimal -> float


def _candidate_row(cand: Candidate) -> CandidateRow:
    return CandidateRow(
        domain=cand.domain,
        composite_score=_as_float(cand.composite_score),
        current_status=cand.current_status,
        availability_confidence=cand.availability_confidence,
        open_pagerank=_as_float(cand.open_pagerank),
        hard_filtered=bool(cand.hard_filtered),
        hard_filter_reason=cand.hard_filter_reason,
        top_reasons=list(cand.top_reasons or []),
    )


async def fetch_shortlist(limit: int | None = None) -> list[ShortlistItem]:
    """Today's acquisition-backed research queue; never an instruction to buy."""
    cap = limit or settings.digest_max_items
    out: list[ShortlistItem] = []
    async with session_scope() as session:
        active_listing = exists(
            select(MarketplaceListing.id).where(
                MarketplaceListing.candidate_id == Candidate.id,
                MarketplaceListing.listing_status == "active",
                MarketplaceListing.drop_date >= dt.date.today() - dt.timedelta(days=1),
            )
        )
        latest_outcome = aliased(Outcome)
        terminal_outcome = aliased(Outcome)
        latest_outcome_id = (
            select(latest_outcome.id)
            .where(latest_outcome.candidate_id == Candidate.id)
            .order_by(desc(latest_outcome.decided_at), desc(latest_outcome.id))
            .limit(1)
            .correlate_except(latest_outcome)
            .scalar_subquery()
        )
        terminal_decision = exists(
            select(terminal_outcome.id)
            .where(
                terminal_outcome.id == latest_outcome_id,
                terminal_outcome.decision.in_(TERMINAL_DECISIONS),
            )
            .correlate_except(terminal_outcome)
        )
        stmt = (
            select(Candidate, OpportunityAssessment)
            .join(OpportunityAssessment, OpportunityAssessment.candidate_id == Candidate.id)
            .where(
                OpportunityAssessment.model_version == MODEL_VERSION,
                OpportunityAssessment.verdict == "research",
                active_listing,
                ~terminal_decision,
            )
            .order_by(desc(OpportunityAssessment.overall_score))
            .limit(cap)
        )
        for cand, assessment in (await session.execute(stmt)).all():
            listing = (
                await session.execute(
                    select(MarketplaceListing)
                    .where(
                        MarketplaceListing.candidate_id == cand.id,
                        MarketplaceListing.listing_status == "active",
                        MarketplaceListing.drop_date >= dt.date.today() - dt.timedelta(days=1),
                    )
                    .order_by(desc(MarketplaceListing.last_seen))
                    .limit(1)
                )
            ).scalar_one_or_none()
            if listing is None:
                continue
            out.append(
                ShortlistItem(
                    domain=cand.domain,
                    composite_score=_as_float(assessment.overall_score),
                    current_status=cand.current_status,
                    quote_price_micros=(
                        listing.current_price_micros or listing.minimum_price_micros
                    ),
                    top_reasons=list(assessment.reasons or []),
                    closes_at=str(listing.closes_at) if listing.closes_at else None,
                    missing_evidence=list(assessment.missing_evidence or []),
                )
            )
    return out


async def fetch_candidates(
    min_score: float | None = None,
    status: str | None = None,
    limit: int = 15,
    offset: int = 0,
) -> list[CandidateRow]:
    async with session_scope() as session:
        stmt = select(Candidate)
        if min_score is not None:
            stmt = stmt.where(Candidate.composite_score >= min_score)
        if status:
            stmt = stmt.where(Candidate.current_status == status)
        stmt = (
            stmt.order_by(desc(Candidate.composite_score), Candidate.id).limit(limit).offset(offset)
        )
        return [_candidate_row(c) for c in (await session.execute(stmt)).scalars().all()]


async def fetch_candidate_detail(domain: str) -> CandidateDetail | None:
    async with session_scope() as session:
        cand = (
            await session.execute(select(Candidate).where(Candidate.domain == domain))
        ).scalar_one_or_none()
        if cand is None:
            return None
        mentions = (
            (
                await session.execute(
                    select(SourceMention)
                    .where(SourceMention.candidate_id == cand.id)
                    .order_by(desc(SourceMention.observed_at))
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        avail = (
            (
                await session.execute(
                    select(AvailabilityCheck)
                    .where(AvailabilityCheck.candidate_id == cand.id)
                    .order_by(desc(AvailabilityCheck.observed_at))
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        wb = (
            (
                await session.execute(
                    select(WaybackSnapshot)
                    .where(WaybackSnapshot.candidate_id == cand.id)
                    .order_by(desc(WaybackSnapshot.observed_at))
                    .limit(3)
                )
            )
            .scalars()
            .all()
        )
        rq = (
            await session.execute(
                select(RegistrarQuote)
                .where(RegistrarQuote.candidate_id == cand.id)
                .order_by(desc(RegistrarQuote.observed_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        outcome = (
            await session.execute(
                select(Outcome)
                .where(Outcome.candidate_id == cand.id)
                .order_by(desc(Outcome.decided_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        return CandidateDetail(
            candidate=_candidate_row(cand),
            mentions=[
                MentionRow(
                    source_url=m.source_url,
                    context_type=m.context_type,
                    context_snippet=m.context_snippet,
                )
                for m in mentions
            ],
            availability=[
                AvailabilityRow(
                    source=a.source, status=a.status, is_authoritative=a.is_authoritative
                )
                for a in avail
            ],
            wayback=[
                WaybackRow(
                    first_capture=str(w.first_capture) if w.first_capture else None,
                    last_capture=str(w.last_capture) if w.last_capture else None,
                    capture_count=w.capture_count,
                )
                for w in wb
            ],
            latest_quote_micros=rq.quote_price_micros if rq is not None else None,
            latest_decision=outcome.decision if outcome is not None else None,
        )


async def record_outcome(
    domain: str, decision: str, notes: str | None = None, pass_reason: str | None = None
) -> bool:
    """Append an operator decision. Returns False if the domain is unknown."""
    if decision not in DECISIONS:
        raise ValueError(f"invalid decision: {decision}")
    async with session_scope() as session:
        cand = (
            await session.execute(select(Candidate).where(Candidate.domain == domain))
        ).scalar_one_or_none()
        if cand is None:
            return False
        session.add(
            Outcome(candidate_id=cand.id, decision=decision, pass_reason=pass_reason, notes=notes)
        )
        return True


async def current_config() -> ConfigInfo:
    async with session_scope() as session:
        sw = (
            await session.execute(
                select(ScoringWeights).order_by(desc(ScoringWeights.version)).limit(1)
            )
        ).scalar_one_or_none()
    weights: dict[str, float] = {}
    if sw is not None:
        weights = {str(k): float(v) for k, v in sw.weights_json.items()}
    return ConfigInfo(
        weights_version=sw.version if sw is not None else None,
        weights=weights,
        digest_min_score=settings.digest_min_score,
        digest_max_items=settings.digest_max_items,
        premium_ceiling_usd=settings.premium_ceiling_usd,
        opr_min_authority=settings.opr_min_authority,
    )


async def candidate_domains(prefix: str, limit: int = 20) -> list[str]:
    """Domain names for slash-command autocomplete."""
    async with session_scope() as session:
        stmt = select(Candidate.domain).order_by(desc(Candidate.composite_score)).limit(limit)
        if prefix:
            stmt = (
                select(Candidate.domain).where(Candidate.domain.ilike(f"%{prefix}%")).limit(limit)
            )
        return [str(d) for d in (await session.execute(stmt)).scalars().all()]
