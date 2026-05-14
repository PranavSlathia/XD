"""FastAPI dashboard backend (PRD §4.6).

Endpoints (all JSON via ORJSONResponse):
    GET  /health                    — db + redis liveness
    GET  /api/candidates            — paginated list
    GET  /api/candidates/{domain}   — detail + evidence
    POST /api/decisions             — operator decision
    GET  /api/scoring-weights       — current
    POST /api/scoring-weights       — new version (kicks scoring via redis pubsub)
    GET  /api/digest/today          — digest-eligible candidates
    GET  /api/events                — SSE stream from redis pub/sub
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import orjson
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import ORJSONResponse, StreamingResponse
from sqlalchemy import desc, select
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

DIGEST_CHANNEL = "dh:candidate-events"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    setup_sentry(service="api")
    setup_tracing(service="api")
    log.info("api.startup")
    yield
    await get_engine().dispose()
    log.info("api.shutdown")


app = FastAPI(
    title="Domain Hunter API",
    default_response_class=ORJSONResponse,
    lifespan=_lifespan,
)
instrument_fastapi(app)

# Prometheus exporter — best-effort; safe if dependency is absent.
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
except Exception as e:
    log.warning("api.prometheus.unavailable", error=str(e))


# --------------------------------------------------------------------------- #
# Dependency helpers
# --------------------------------------------------------------------------- #

async def _session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as s:
        yield s


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #

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
        import redis.asyncio as redis_async

        client = redis_async.from_url(settings.redis_url, socket_connect_timeout=2)
        try:
            await client.ping()
            return True
        finally:
            await client.aclose()
    except Exception as e:
        log.warning("api.health.redis_error", error=str(e))
        return False


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    db_ok, redis_ok = await asyncio.gather(_check_db(), _check_redis())
    return HealthResponse(ok=db_ok and redis_ok, db=db_ok, redis=redis_ok)


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #

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
    domain: str, session: AsyncSession = Depends(_session)
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


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #

@app.post("/api/decisions", response_model=DecisionResponse, status_code=201)
async def create_decision(
    body: DecisionCreate, session: AsyncSession = Depends(_session)
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


# --------------------------------------------------------------------------- #
# Scoring weights
# --------------------------------------------------------------------------- #

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
    body: ScoringWeightsCreate, session: AsyncSession = Depends(_session)
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
    await session.flush()
    # Best-effort kick the scoring worker via Redis pub/sub.
    try:
        import redis.asyncio as redis_async

        client = redis_async.from_url(settings.redis_url, socket_connect_timeout=2)
        try:
            await client.publish(DIGEST_CHANNEL, orjson.dumps({"kind": "weights_bumped", "version": next_version}).decode())
        finally:
            await client.aclose()
    except Exception as e:
        log.warning("api.weights.publish_failed", error=str(e))
    return ScoringWeightsItem(
        version=row.version,
        weights_json={k: float(v) for k, v in row.weights_json.items()},
        notes=row.notes,
        created_at=row.created_at,
    )


# --------------------------------------------------------------------------- #
# Digest
# --------------------------------------------------------------------------- #

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
        if rq and rq.quote_price_micros and rq.quote_price_micros >= settings.premium_ceiling_micros:
            continue
        out.append(
            CandidateDigestItem(
                domain=cand.domain,
                composite_score=float(cand.composite_score) if cand.composite_score else None,
                current_status=cand.current_status,
                quote_price_micros=rq.quote_price_micros if rq else None,
                top_reasons=[],
            )
        )
    return out


# --------------------------------------------------------------------------- #
# SSE
# --------------------------------------------------------------------------- #

@app.get("/api/events")
async def events() -> StreamingResponse:
    async def _stream() -> AsyncIterator[bytes]:
        try:
            import redis.asyncio as redis_async

            client = redis_async.from_url(settings.redis_url)
            pubsub = client.pubsub()
            await pubsub.subscribe(DIGEST_CHANNEL)
            try:
                async for message in pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    data = message.get("data")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8", "replace")
                    yield f"data: {data}\n\n".encode()
            finally:
                await pubsub.unsubscribe(DIGEST_CHANNEL)
                await pubsub.aclose()
                await client.aclose()
        except Exception as e:
            log.warning("api.sse.error", error=str(e))
            yield b"event: error\ndata: redis unavailable\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
