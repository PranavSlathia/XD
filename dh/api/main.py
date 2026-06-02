"""Headless FastAPI surface for the external agent layer.

Endpoints are intentionally programmatic only. Humans interact with Domain Hunter
through Quip/Codex/Gemini agents, which call this API when they need candidate,
digest, decision, or scoring-weight data.
"""
from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import redis.asyncio as redis_async
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dh.api.schemas import (
    AvailabilityEvidence,
    CandidateDetail,
    CandidateDigestItem,
    CandidateListItem,
    DecisionCreate,
    DecisionResponse,
    HealthResponse,
    MentionItem,
    ScoringWeightsCreate,
    ScoringWeightsItem,
    WaybackEvidence,
)
from dh.config import settings
from dh.db.engine import get_engine, session_scope
from dh.db.models import (
    AvailabilityCheck,
    Candidate,
    Outcome,
    RegistrarQuote,
    ScoringWeights,
    SourceMention,
    WaybackSnapshot,
)
from dh.logging import configure_logging, log
from dh.observability import instrument_fastapi, setup_sentry, setup_tracing


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
    session: AsyncSession = Depends(_session),
) -> list[CandidateListItem]:
    stmt = select(Candidate)
    if min_score is not None:
        stmt = stmt.where(Candidate.composite_score >= min_score)
    if status:
        stmt = stmt.where(Candidate.current_status == status)
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
        await session.execute(
            select(SourceMention)
            .where(SourceMention.candidate_id == cand.id)
            .order_by(desc(SourceMention.observed_at))
            .limit(50)
        )
    ).scalars().all()
    avail = (
        await session.execute(
            select(AvailabilityCheck)
            .where(AvailabilityCheck.candidate_id == cand.id)
            .order_by(desc(AvailabilityCheck.observed_at))
            .limit(20)
        )
    ).scalars().all()
    wb = (
        await session.execute(
            select(WaybackSnapshot)
            .where(WaybackSnapshot.candidate_id == cand.id)
            .order_by(desc(WaybackSnapshot.observed_at))
            .limit(10)
        )
    ).scalars().all()
    base = CandidateListItem.model_validate(cand)
    return CandidateDetail(
        **base.model_dump(),
        mentions=[MentionItem.model_validate(m) for m in mentions],
        availability_history=[AvailabilityEvidence.model_validate(a) for a in avail],
        wayback_history=[WaybackEvidence.model_validate(w) for w in wb],
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
        await session.execute(select(ScoringWeights).order_by(desc(ScoringWeights.version)).limit(1))
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
        await session.execute(select(ScoringWeights).order_by(desc(ScoringWeights.version)).limit(1))
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


DIGEST_STATUSES = ("available", "pending_delete", "redemption_period", "expiring_soon")


@app.get("/api/digest/today", response_model=list[CandidateDigestItem])
async def digest_today(
    session: AsyncSession = Depends(_session),
) -> list[CandidateDigestItem]:
    stmt = (
        select(Candidate)
        .where(
            Candidate.composite_score >= settings.digest_min_score,
            Candidate.hard_filtered.is_(False),
            Candidate.availability_confidence == "authoritative",
            Candidate.current_status.in_(DIGEST_STATUSES),
        )
        .order_by(desc(Candidate.composite_score))
        .limit(settings.digest_max_items)
    )
    rows = (await session.execute(stmt)).scalars().all()
    out: list[CandidateDigestItem] = []
    for cand in rows:
        rq = (
            await session.execute(
                select(RegistrarQuote)
                .where(RegistrarQuote.candidate_id == cand.id)
                .order_by(desc(RegistrarQuote.observed_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if rq is None:
            continue
        if rq.is_premium is True:
            continue
        if rq.quote_price_micros is None:
            continue
        if rq.quote_price_micros >= settings.premium_ceiling_micros:
            continue
        out.append(
            CandidateDigestItem(
                domain=cand.domain,
                composite_score=float(cand.composite_score) if cand.composite_score else None,
                current_status=cand.current_status,
                quote_price_micros=rq.quote_price_micros,
                top_reasons=cand.top_reasons or [],
            )
        )
    return out
