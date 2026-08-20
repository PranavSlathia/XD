"""Headless FastAPI surface for the external agent layer.

Endpoints are intentionally programmatic only. Humans interact with Domain Hunter
through Quip/Codex/Gemini agents, which call this API when they need candidate,
digest, decision, or scoring-weight data.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import redis.asyncio as redis_async
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from sqlalchemy import desc, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Exists

from dh.api.schemas import (
    AvailabilityEvidence,
    CandidateDetail,
    CandidateDigestItem,
    CandidateListItem,
    DecisionCreate,
    DecisionResponse,
    DiscoveryRunItem,
    HealthResponse,
    MarketplaceEvidence,
    MentionItem,
    OpportunityItem,
    PipelineStatus,
    ScoringWeightsCreate,
    ScoringWeightsItem,
    WaybackEvidence,
)
from dh.api.v1 import router as v1_router
from dh.config import settings
from dh.db.engine import get_engine, session_scope
from dh.db.models import (
    AvailabilityCheck,
    Candidate,
    DiscoveryRun,
    MarketplaceListing,
    OpportunityAssessment,
    Outcome,
    ScoringWeights,
    SourceMention,
    WaybackSnapshot,
)
from dh.logging import configure_logging, log
from dh.observability import instrument_fastapi, setup_sentry, setup_tracing
from dh.opportunity import MODEL_VERSION

TERMINAL_DECISIONS = ("passed", "bought", "lost_to_other")


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    setup_sentry(service="api")
    setup_tracing(service="api")
    log.info("api.startup")
    yield
    await get_engine().dispose()
    log.info("api.shutdown")


app = FastAPI(title="Domain Hunter API", lifespan=_lifespan)
app.include_router(v1_router)
instrument_fastapi(app)

# Prometheus exporter — best-effort; safe if dependency is absent.
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
except Exception as e:
    log.warning("api.prometheus.unavailable", error=str(e))


async def _session() -> AsyncGenerator[AsyncSession, None]:
    async with session_scope() as s:
        yield s


async def _check_db() -> bool:
    try:
        async with session_scope() as session:
            await session.execute(select(1))
        return True
    except Exception as e:
        log.warning("api.health.db_error", error=str(e))
        return False


async def _check_redis() -> bool:
    try:
        client = redis_async.from_url(  # pyright: ignore[reportUnknownMemberType]
            settings.redis_url,
            socket_connect_timeout=2,
        )
        try:
            ping_result = cast(
                object,
                client.ping(),  # pyright: ignore[reportUnknownMemberType]
            )
            if inspect.isawaitable(ping_result):
                ping_result = await ping_result
            return bool(ping_result)
        finally:
            await client.aclose()
    except Exception as e:
        log.warning("api.health.redis_error", error=str(e))
        return False


@app.get("/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    db_ok, redis_ok = await asyncio.gather(_check_db(), _check_redis())
    if not (db_ok and redis_ok):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(ok=db_ok and redis_ok, db=db_ok, redis=redis_ok)


@app.get("/api/candidates", response_model=list[CandidateListItem])
async def list_candidates(
    min_score: float | None = Query(default=None, ge=0, le=100),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_filtered: bool = Query(default=False),
    session: AsyncSession = Depends(_session),
) -> list[CandidateListItem]:
    stmt = select(Candidate)
    if min_score is not None:
        stmt = stmt.where(Candidate.composite_score >= min_score)
    if status:
        stmt = stmt.where(Candidate.current_status == status)
    if not include_filtered:
        stmt = stmt.where(Candidate.hard_filtered.is_(False))
    stmt = stmt.order_by(desc(Candidate.composite_score), Candidate.id).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()
    return [CandidateListItem.model_validate(r) for r in rows]


@app.get("/api/candidates/{domain}", response_model=CandidateDetail)
async def get_candidate(
    domain: str,
    session: AsyncSession = Depends(_session),
) -> CandidateDetail:
    cand = (
        await session.execute(select(Candidate).where(Candidate.domain == domain))
    ).scalar_one_or_none()
    if cand is None:
        raise HTTPException(status_code=404, detail="candidate not found")

    mentions = (
        (
            await session.execute(
                select(SourceMention)
                .where(SourceMention.candidate_id == cand.id)
                .order_by(desc(SourceMention.observed_at))
                .limit(50)
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
                .limit(20)
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
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    base = CandidateListItem.model_validate(cand)
    return CandidateDetail(
        **base.model_dump(),
        mentions=[MentionItem.model_validate(m) for m in mentions],
        availability_history=[AvailabilityEvidence.model_validate(a) for a in avail],
        wayback_history=[WaybackEvidence.model_validate(w) for w in wb],
    )


async def _latest_listings(
    session: AsyncSession,
    candidate_ids: list[int],
    *,
    active_only: bool = False,
) -> dict[int, MarketplaceListing]:
    if not candidate_ids:
        return {}
    stmt = select(MarketplaceListing).where(MarketplaceListing.candidate_id.in_(candidate_ids))
    if active_only:
        stmt = stmt.where(
            MarketplaceListing.listing_status == "active",
            MarketplaceListing.drop_date >= dt.date.today() - dt.timedelta(days=1),
        )
    rows = (
        (
            await session.execute(
                stmt.order_by(
                    MarketplaceListing.candidate_id,
                    desc(MarketplaceListing.last_seen),
                    desc(MarketplaceListing.id),
                )
            )
        )
        .scalars()
        .all()
    )
    latest: dict[int, MarketplaceListing] = {}
    for row in rows:
        latest.setdefault(row.candidate_id, row)
    return latest


async def _latest_wayback(
    session: AsyncSession, candidate_ids: list[int]
) -> dict[int, WaybackSnapshot]:
    if not candidate_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(WaybackSnapshot)
                .where(WaybackSnapshot.candidate_id.in_(candidate_ids))
                .order_by(
                    WaybackSnapshot.candidate_id,
                    desc(WaybackSnapshot.observed_at),
                    desc(WaybackSnapshot.id),
                )
            )
        )
        .scalars()
        .all()
    )
    latest: dict[int, WaybackSnapshot] = {}
    for row in rows:
        latest.setdefault(row.candidate_id, row)
    return latest


def _terminal_decision_exists(
    candidate_id: InstrumentedAttribute[int] | ColumnElement[int],
) -> Exists:
    """Correlated predicate for a candidate's latest human decision."""
    latest_outcome = aliased(Outcome)
    terminal_outcome = aliased(Outcome)
    latest_id = (
        select(latest_outcome.id)
        .where(latest_outcome.candidate_id == candidate_id)
        .order_by(desc(latest_outcome.decided_at), desc(latest_outcome.id))
        .limit(1)
        .correlate_except(latest_outcome)
        .scalar_subquery()
    )
    return exists(
        select(terminal_outcome.id)
        .where(
            terminal_outcome.id == latest_id,
            terminal_outcome.decision.in_(TERMINAL_DECISIONS),
        )
        .correlate_except(terminal_outcome)
    )


async def _latest_outcomes(session: AsyncSession, candidate_ids: list[int]) -> dict[int, Outcome]:
    if not candidate_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(Outcome)
                .where(Outcome.candidate_id.in_(candidate_ids))
                .order_by(
                    Outcome.candidate_id,
                    desc(Outcome.decided_at),
                    desc(Outcome.id),
                )
            )
        )
        .scalars()
        .all()
    )
    latest: dict[int, Outcome] = {}
    for row in rows:
        latest.setdefault(row.candidate_id, row)
    return latest


@app.get("/api/opportunities", response_model=list[OpportunityItem])
async def list_opportunities(
    verdict: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    actionable_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(_session),
) -> list[OpportunityItem]:
    """Evidence-backed research queue. This endpoint never authorizes acquisition."""
    if verdict not in (None, "research", "observe", "reject"):
        raise HTTPException(status_code=422, detail="verdict must be research, observe, or reject")
    active_listing = exists(
        select(MarketplaceListing.id).where(
            MarketplaceListing.candidate_id == Candidate.id,
            MarketplaceListing.listing_status == "active",
            MarketplaceListing.drop_date >= dt.date.today() - dt.timedelta(days=1),
        )
    )
    stmt = (
        select(Candidate, OpportunityAssessment)
        .join(
            OpportunityAssessment,
            OpportunityAssessment.candidate_id == Candidate.id,
        )
        .where(OpportunityAssessment.model_version == MODEL_VERSION)
    )
    if verdict:
        stmt = stmt.where(OpportunityAssessment.verdict == verdict)
    if active_only:
        stmt = stmt.where(active_listing)
    if actionable_only:
        stmt = stmt.where(~_terminal_decision_exists(Candidate.id))
    stmt = (
        stmt.order_by(
            desc(OpportunityAssessment.overall_score),
            Candidate.authority_rank.asc().nulls_last(),
        )
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()
    candidate_ids = [candidate.id for candidate, _assessment in rows]
    listings = await _latest_listings(session, candidate_ids, active_only=active_only)
    wayback = await _latest_wayback(session, candidate_ids)
    outcomes = await _latest_outcomes(session, candidate_ids)
    output: list[OpportunityItem] = []
    for candidate, assessment in rows:
        listing = listings.get(candidate.id)
        wb = wayback.get(candidate.id)
        outcome = outcomes.get(candidate.id)
        acquisition = (
            MarketplaceEvidence(
                marketplace=listing.marketplace,
                acquisition_type=listing.acquisition_type,
                listing_status=listing.listing_status,
                drop_date=listing.drop_date,
                closes_at=listing.closes_at,
                minimum_price_micros=listing.minimum_price_micros,
                current_price_micros=listing.current_price_micros,
                currency=listing.currency,
                listing_url=listing.listing_url,
                last_seen=listing.last_seen,
            )
            if listing
            else None
        )
        output.append(
            OpportunityItem(
                candidate_id=candidate.id,
                domain=candidate.domain,
                verdict=assessment.verdict,
                overall_score=float(assessment.overall_score),
                authority_score=float(assessment.authority_score),
                resale_score=float(assessment.resale_score),
                risk_score=float(assessment.risk_score),
                confidence_score=float(assessment.confidence_score),
                open_pagerank=(
                    float(candidate.open_pagerank) if candidate.open_pagerank is not None else None
                ),
                referring_domains=candidate.referring_domains,
                authority_rank=candidate.authority_rank,
                current_status=candidate.current_status,
                availability_confidence=candidate.availability_confidence,
                reasons=list(assessment.reasons or []),
                rejection_reasons=list(assessment.rejection_reasons or []),
                missing_evidence=list(assessment.missing_evidence or []),
                signals=dict(assessment.signals or {}),
                computed_at=assessment.computed_at,
                latest_decision=outcome.decision if outcome else None,
                acquisition=acquisition,
                wayback=WaybackEvidence.model_validate(wb) if wb else None,
            )
        )
    return output


@app.get("/api/pipeline/status", response_model=PipelineStatus)
async def pipeline_status(session: AsyncSession = Depends(_session)) -> PipelineStatus:
    """Current funnel health and explicit automation safety posture."""
    last_run = (
        await session.execute(select(DiscoveryRun).order_by(desc(DiscoveryRun.started_at)).limit(1))
    ).scalar_one_or_none()
    active_cutoff = dt.date.today() - dt.timedelta(days=1)
    active_where = (
        MarketplaceListing.listing_status == "active",
        MarketplaceListing.drop_date >= active_cutoff,
    )
    active_count = int(
        (
            await session.execute(
                select(func.count(func.distinct(MarketplaceListing.candidate_id))).where(
                    *active_where
                )
            )
        ).scalar_one()
    )

    async def _verdict_count(value: str) -> int:
        return int(
            (
                await session.execute(
                    select(func.count(func.distinct(OpportunityAssessment.candidate_id)))
                    .join(
                        MarketplaceListing,
                        MarketplaceListing.candidate_id == OpportunityAssessment.candidate_id,
                    )
                    .where(
                        OpportunityAssessment.model_version == MODEL_VERSION,
                        OpportunityAssessment.verdict == value,
                        ~_terminal_decision_exists(OpportunityAssessment.candidate_id),
                        *active_where,
                    )
                )
            ).scalar_one()
        )

    # AsyncSession is intentionally used serially; it does not permit
    # overlapping operations on one connection.
    research_count = await _verdict_count("research")
    observe_count = await _verdict_count("observe")
    reject_count = await _verdict_count("reject")
    manually_closed = int(
        (
            await session.execute(
                select(func.count(func.distinct(Candidate.id)))
                .join(MarketplaceListing, MarketplaceListing.candidate_id == Candidate.id)
                .where(_terminal_decision_exists(Candidate.id), *active_where)
            )
        ).scalar_one()
    )
    rdap_pending = int(
        (
            await session.execute(
                select(func.count(func.distinct(Candidate.id)))
                .join(MarketplaceListing, MarketplaceListing.candidate_id == Candidate.id)
                .where(
                    Candidate.availability_confidence.is_distinct_from("authoritative"),
                    ~_terminal_decision_exists(Candidate.id),
                    *active_where,
                )
            )
        ).scalar_one()
    )
    wayback_pending = int(
        (
            await session.execute(
                select(func.count(func.distinct(Candidate.id)))
                .join(MarketplaceListing, MarketplaceListing.candidate_id == Candidate.id)
                .where(
                    *active_where,
                    ~_terminal_decision_exists(Candidate.id),
                    ~exists(
                        select(WaybackSnapshot.id).where(
                            WaybackSnapshot.candidate_id == Candidate.id
                        )
                    ),
                )
            )
        ).scalar_one()
    )
    return PipelineStatus(
        last_run=DiscoveryRunItem.model_validate(last_run, from_attributes=True)
        if last_run
        else None,
        active_acquisition_candidates=active_count,
        research_queue=research_count,
        observe_queue=observe_count,
        rejected=reject_count,
        manually_closed=manually_closed,
        rdap_confirmation_pending=rdap_pending,
        wayback_review_pending=wayback_pending,
    )


@app.post("/api/decisions", response_model=DecisionResponse, status_code=201)
async def create_decision(
    body: DecisionCreate,
    session: AsyncSession = Depends(_session),
) -> DecisionResponse:
    cand = (
        await session.execute(select(Candidate).where(Candidate.domain == body.domain))
    ).scalar_one_or_none()
    if cand is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    out = Outcome(
        candidate_id=cand.id,
        decision=body.decision,
        pass_reason=body.pass_reason,
        notes=body.notes,
        acquisition_cost_usd=body.acquisition_cost_usd,
        acquisition_channel=body.acquisition_channel,
    )
    session.add(out)
    await session.flush()
    return DecisionResponse(
        id=out.id,
        candidate_id=out.candidate_id,
        decision=out.decision,
        decided_at=out.decided_at,
    )


@app.get("/api/scoring-weights", response_model=ScoringWeightsItem)
async def get_scoring_weights(
    session: AsyncSession = Depends(_session),
) -> ScoringWeightsItem:
    row = (
        await session.execute(
            select(ScoringWeights).order_by(desc(ScoringWeights.version)).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no scoring_weights row")
    return ScoringWeightsItem(
        version=row.version,
        weights_json={k: float(v) for k, v in (row.weights_json or {}).items()},
        notes=row.notes,
        created_at=row.created_at,
    )


@app.post("/api/scoring-weights", response_model=ScoringWeightsItem, status_code=201)
async def create_scoring_weights(
    body: ScoringWeightsCreate,
    session: AsyncSession = Depends(_session),
) -> ScoringWeightsItem:
    latest_row = (
        await session.execute(
            select(ScoringWeights).order_by(desc(ScoringWeights.version)).limit(1)
        )
    ).scalar_one_or_none()
    next_version = (latest_row.version + 1) if latest_row else 1
    row = ScoringWeights(
        version=next_version,
        weights_json=body.weights_json,
        notes=body.notes,
    )
    session.add(row)
    await session.execute(update(Candidate).values(score_version=None))
    await session.flush()
    log.info("api.scoring_weights.created", version=next_version)
    return ScoringWeightsItem(
        version=row.version,
        weights_json={k: float(v) for k, v in row.weights_json.items()},
        notes=row.notes,
        created_at=row.created_at,
    )


@app.get("/api/digest/today", response_model=list[CandidateDigestItem])
async def digest_today(
    session: AsyncSession = Depends(_session),
) -> list[CandidateDigestItem]:
    active_listing = exists(
        select(MarketplaceListing.id).where(
            MarketplaceListing.candidate_id == Candidate.id,
            MarketplaceListing.listing_status == "active",
            MarketplaceListing.drop_date >= dt.date.today() - dt.timedelta(days=1),
        )
    )
    stmt = (
        select(Candidate, OpportunityAssessment)
        .join(OpportunityAssessment, OpportunityAssessment.candidate_id == Candidate.id)
        .where(
            OpportunityAssessment.model_version == MODEL_VERSION,
            OpportunityAssessment.verdict == "research",
            active_listing,
            ~_terminal_decision_exists(Candidate.id),
        )
        .order_by(desc(OpportunityAssessment.overall_score))
        .limit(settings.digest_max_items)
    )
    rows = (await session.execute(stmt)).all()
    listings = await _latest_listings(
        session,
        [candidate.id for candidate, _ in rows],
        active_only=True,
    )
    out: list[CandidateDigestItem] = []
    for cand, assessment in rows:
        listing = listings.get(cand.id)
        if listing is None or listing.listing_status != "active":
            continue
        price = listing.current_price_micros or listing.minimum_price_micros
        out.append(
            CandidateDigestItem(
                domain=cand.domain,
                composite_score=float(assessment.overall_score),
                current_status=cand.current_status,
                quote_price_micros=price,
                closes_at=listing.closes_at,
                verdict=assessment.verdict,
                missing_evidence=list(assessment.missing_evidence or []),
                top_reasons=list(assessment.reasons or []),
            )
        )
    return out
