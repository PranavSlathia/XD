from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import AsyncGenerator, Sequence
from typing import Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dh.api.dependencies import v1_session
from dh.api.schemas_v1 import (
    CandidateDetailV1,
    CandidatePageV1,
    CandidateSummaryV1,
    ConfigCreate,
    ConfigVersionItem,
    DeviceItem,
    DossierItem,
    EventItem,
    GateItem,
    JobCreate,
    JobItem,
    LaneAssessmentItem,
    LinkEvidenceItem,
    PairingComplete,
    PairingResult,
    PortfolioOutcomeCreate,
    PortfolioOutcomeItem,
    QuoteItem,
    ReviewCreate,
    ReviewItem,
    RunItemV1,
    TodayResponse,
    WorkerItem,
)
from dh.config import settings
from dh.db.engine import session_scope
from dh.db.models import (
    Candidate,
    CandidateDossier,
    CandidateEvent,
    CandidateReview,
    CrawlRun,
    DeviceCredential,
    DiscoveryRun,
    EngineConfigVersion,
    EventReadReceipt,
    GateResult,
    LaneAssessment,
    LinkObservation,
    OperatorJob,
    PortfolioOutcome,
    RegistrarQuote,
    SourcePage,
    WorkerHeartbeat,
)
from dh.engine.configuration import EngineConfig, config_diff, get_active_config
from dh.jobs import SAFE_JOB_KINDS, new_job_id
from dh.lanes.gates import GateEvidence, evaluate_readiness, review_transition_allowed
from dh.lanes.types import GateState, Lane
from dh.security.device_auth import DeviceIdentity, complete_pairing, require_device

router = APIRouter(prefix="/api/v1", tags=["XD v1"])


def _lane_item(row: LaneAssessment) -> LaneAssessmentItem:
    return LaneAssessmentItem(
        lane=cast(Any, row.lane),
        name_subtype=row.name_subtype,
        state=row.state,
        screen_passed=row.screen_passed,
        lane_score=float(row.lane_score) if row.lane_score is not None else None,
        model_version=row.model_version,
        config_version=row.config_version,
        computed_at=row.computed_at,
        signals=row.signals or {},
        reasons=row.reasons or [],
        missing_evidence=row.missing_evidence or [],
    )


async def _assessment_map(
    session: AsyncSession, candidate_ids: Sequence[int], config_version: int
) -> dict[int, list[LaneAssessment]]:
    if not candidate_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(LaneAssessment)
                .where(
                    LaneAssessment.candidate_id.in_(candidate_ids),
                    LaneAssessment.config_version == config_version,
                    LaneAssessment.screen_passed.is_(True),
                )
                .order_by(LaneAssessment.candidate_id, LaneAssessment.lane)
            )
        )
        .scalars()
        .all()
    )
    result: dict[int, list[LaneAssessment]] = {}
    for row in rows:
        result.setdefault(row.candidate_id, []).append(row)
    return result


def _summary(candidate: Candidate, assessments: Sequence[LaneAssessment]) -> CandidateSummaryV1:
    by_lane = {row.lane: row for row in assessments}
    lanes = [cast(Any, lane) for lane in ("name", "authority") if lane in by_lane]
    name = by_lane.get("name")
    authority = by_lane.get("authority")
    return CandidateSummaryV1(
        id=candidate.id,
        domain=candidate.domain,
        lanes=lanes,
        # Screening puts a domain into one or both Research lanes.  "Hybrid"
        # is reserved for the stronger claim that both lanes independently
        # completed qualification; merely entering two screens is not enough.
        hybrid=(
            name is not None
            and authority is not None
            and name.state == "qualified"
            and authority.state == "qualified"
        ),
        name_subtype=name.name_subtype if name else None,
        name_score=float(name.lane_score) if name and name.lane_score is not None else None,
        authority_score=(
            float(authority.lane_score)
            if authority and authority.lane_score is not None
            else None
        ),
        review_state=cast(Any, candidate.review_state),
        lifecycle_state=candidate.lifecycle_state,
        current_status=candidate.current_status,
        availability_confidence=candidate.availability_confidence,
        promoted_at=candidate.promoted_at,
        last_observed=candidate.last_observed,
        dossier_updated_at=candidate.dossier_updated_at,
    )


async def _summaries(
    session: AsyncSession, candidates: Sequence[Candidate], config_version: int
) -> list[CandidateSummaryV1]:
    mapping = await _assessment_map(session, [row.id for row in candidates], config_version)
    return [_summary(row, mapping.get(row.id, ())) for row in candidates]


@router.get("/today", response_model=TodayResponse)
async def today(
    _device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> TodayResponse:
    config_row, _config = await get_active_config(session)
    candidates = (
        (
            await session.execute(
                select(Candidate)
                .where(
                    Candidate.promoted_at.is_not(None),
                    Candidate.review_state.in_(("research", "ready")),
                )
                .order_by(
                    desc(Candidate.review_state == "ready"),
                    Candidate.dossier_updated_at.desc().nullslast(),
                    Candidate.last_observed.desc(),
                )
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    unread = (
        await session.execute(
            select(func.count(CandidateEvent.id))
            .outerjoin(EventReadReceipt, EventReadReceipt.event_id == CandidateEvent.id)
            .where(
                CandidateEvent.candidate_id.is_not(None),
                EventReadReceipt.event_id.is_(None),
            )
        )
    ).scalar_one()
    stale_before = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=90)
    stale_workers = (
        await session.execute(
            select(func.count(WorkerHeartbeat.worker_name)).where(
                WorkerHeartbeat.observed_at < stale_before
            )
        )
    ).scalar_one()
    summaries = await _summaries(session, candidates, config_row.version)
    return TodayResponse(
        generated_at=dt.datetime.now(dt.UTC),
        system_health="degraded" if int(stale_workers) else "healthy",
        unread_events=int(unread),
        most_urgent_domain=summaries[0].domain if summaries else None,
        candidates=summaries,
    )


@router.get("/candidates", response_model=CandidatePageV1)
async def candidates(
    lane: str | None = Query(default=None, pattern="^(name|authority|hybrid)$"),
    state: str | None = Query(default=None, pattern="^(ready|research|reject)$"),
    search: str | None = Query(default=None, max_length=253),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> CandidatePageV1:
    config_row, _config = await get_active_config(session)
    stmt = select(Candidate).where(Candidate.promoted_at.is_not(None))
    if state:
        stmt = stmt.where(Candidate.review_state == state)
    if search:
        stmt = stmt.where(Candidate.domain.ilike(f"%{search.lower()}%"))
    if cursor:
        try:
            stmt = stmt.where(Candidate.id < int(cursor))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="cursor must be a candidate id") from exc
    if lane in {"name", "authority"}:
        stmt = stmt.where(
            select(LaneAssessment.id)
            .where(
                LaneAssessment.candidate_id == Candidate.id,
                LaneAssessment.config_version == config_row.version,
                LaneAssessment.lane == lane,
                LaneAssessment.screen_passed.is_(True),
            )
            .exists()
        )
    elif lane == "hybrid":
        for item in ("name", "authority"):
            stmt = stmt.where(
                select(LaneAssessment.id)
                .where(
                    LaneAssessment.candidate_id == Candidate.id,
                    LaneAssessment.config_version == config_row.version,
                    LaneAssessment.lane == item,
                    LaneAssessment.state == "qualified",
                )
                .exists()
            )
    rows = (
        (await session.execute(stmt.order_by(Candidate.id.desc()).limit(limit + 1)))
        .scalars()
        .all()
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    return CandidatePageV1(
        items=await _summaries(session, page_rows, config_row.version),
        next_cursor=str(page_rows[-1].id) if has_more and page_rows else None,
    )


@router.get("/candidates/{candidate_id}", response_model=CandidateDetailV1)
async def candidate_detail(
    candidate_id: int,
    _device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> CandidateDetailV1:
    config_row, _config = await get_active_config(session)
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None or candidate.promoted_at is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    assessments = (
        (
            await session.execute(
                select(LaneAssessment)
                .where(
                    LaneAssessment.candidate_id == candidate_id,
                    LaneAssessment.config_version == config_row.version,
                    LaneAssessment.screen_passed.is_(True),
                )
                .order_by(LaneAssessment.lane)
            )
        )
        .scalars()
        .all()
    )
    gates = (
        (
            await session.execute(
                select(GateResult)
                .where(
                    GateResult.candidate_id == candidate_id,
                    GateResult.config_version == config_row.version,
                )
                .order_by(GateResult.lane, GateResult.gate_key)
            )
        )
        .scalars()
        .all()
    )
    dossiers = (
        (
            await session.execute(
                select(CandidateDossier)
                .where(
                    CandidateDossier.candidate_id == candidate_id,
                    CandidateDossier.config_version == config_row.version,
                )
                .order_by(CandidateDossier.lane)
            )
        )
        .scalars()
        .all()
    )
    link_rows = (
        await session.execute(
            select(LinkObservation, SourcePage)
            .join(SourcePage, SourcePage.id == LinkObservation.source_page_id)
            .where(LinkObservation.candidate_id == candidate_id)
            .order_by(LinkObservation.last_seen.desc())
            .limit(200)
        )
    ).all()
    quotes = (
        (
            await session.execute(
                select(RegistrarQuote)
                .where(RegistrarQuote.candidate_id == candidate_id)
                .order_by(RegistrarQuote.observed_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    reviews = (
        (
            await session.execute(
                select(CandidateReview)
                .where(CandidateReview.candidate_id == candidate_id)
                .order_by(CandidateReview.decided_at.desc(), CandidateReview.id.desc())
            )
        )
        .scalars()
        .all()
    )
    summary = _summary(candidate, assessments)
    return CandidateDetailV1(
        **summary.model_dump(),
        assessments=[_lane_item(row) for row in assessments],
        gates=[
            GateItem(
                lane=row.lane,
                gate_key=row.gate_key,
                state=cast(Any, row.state),
                fatal=row.fatal,
                details=row.details,
                evidence_refs=row.evidence_refs or [],
                evaluated_at=row.evaluated_at,
            )
            for row in gates
        ],
        dossiers=[
            DossierItem(
                lane=cast(Any, row.lane),
                status=row.status,
                generated_at=row.generated_at,
                thesis=row.thesis,
                buyer_thesis=row.buyer_thesis or {},
                comparable_sales=row.comparable_sales or [],
                risks=row.risks or [],
                evidence_summary=row.evidence_summary or {},
            )
            for row in dossiers
        ],
        links=[
            LinkEvidenceItem(
                source_url=page.url,
                source_domain=page.host,
                target_url=observation.target_url,
                anchor_text=observation.anchor_text,
                context_text=observation.context_text,
                semantic_location=observation.semantic_location,
                rel_flags=observation.rel_flags or [],
                is_editorial=observation.is_editorial,
                currently_live=observation.currently_live,
                last_seen=observation.last_seen,
            )
            for observation, page in link_rows
        ],
        quotes=[
            QuoteItem(
                registrar=row.registrar,
                availability_status=row.availability_status,
                price_class=row.price_class,
                quote_price_micros=row.quote_price_micros,
                quote_currency=row.quote_currency,
                observed_at=row.observed_at,
                expires_at=row.expires_at,
            )
            for row in quotes
        ],
        reviews=[ReviewItem.model_validate(row) for row in reviews],
    )


@router.post("/candidates/{candidate_id}/reviews", response_model=ReviewItem)
async def review_candidate(
    candidate_id: int,
    body: ReviewCreate,
    device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> ReviewItem:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None or candidate.promoted_at is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    if not review_transition_allowed(candidate.review_state, body.decision):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rejected candidates must be explicitly reopened into Research first",
        )
    config_row, _config = await get_active_config(session)
    assessments = (
        (
            await session.execute(
                select(LaneAssessment).where(
                    LaneAssessment.candidate_id == candidate_id,
                    LaneAssessment.config_version == config_row.version,
                    LaneAssessment.screen_passed.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    gates = (
        (
            await session.execute(
                select(GateResult).where(
                    GateResult.candidate_id == candidate_id,
                    GateResult.config_version == config_row.version,
                )
            )
        )
        .scalars()
        .all()
    )
    dossiers = (
        (
            await session.execute(
                select(CandidateDossier).where(
                    CandidateDossier.candidate_id == candidate_id,
                    CandidateDossier.config_version == config_row.version,
                )
            )
        )
        .scalars()
        .all()
    )
    readiness = evaluate_readiness(
        {Lane(row.lane) for row in assessments},
        [
            GateEvidence(row.lane, row.gate_key, GateState(row.state), row.fatal)
            for row in gates
        ],
    )
    qualified_lanes = {Lane(row.lane) for row in assessments if row.state == "qualified"}
    complete_dossiers = {
        Lane(row.lane) for row in dossiers if row.status == "complete"
    }
    eligible_lanes = set(readiness.ready_lanes) & qualified_lanes & complete_dossiers
    if body.decision == "ready" and not eligible_lanes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "candidate cannot be Ready until at least one lane independently "
                    "qualifies with a complete dossier and every required gate passed"
                ),
                "pending": readiness.pending,
                "failed": readiness.failed,
                "fatal": readiness.fatal_failures,
                "unqualified_lanes": sorted(
                    lane.value for lane in set(readiness.ready_lanes) - qualified_lanes
                ),
                "incomplete_dossiers": sorted(
                    lane.value for lane in set(readiness.ready_lanes) - complete_dossiers
                ),
            },
        )
    if body.decision == "reject" and not body.reason:
        raise HTTPException(status_code=422, detail="Reject requires a reason")
    latest = (
        await session.execute(
            select(CandidateReview)
            .where(CandidateReview.candidate_id == candidate_id)
            .order_by(CandidateReview.decided_at.desc(), CandidateReview.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    review = CandidateReview(
        candidate_id=candidate_id,
        decision=body.decision,
        reason=body.reason,
        notes=body.notes,
        device_id=device.id,
        reopens_review_id=(
            latest.id
            if body.decision == "research" and latest is not None and latest.decision == "reject"
            else None
        ),
    )
    session.add(review)
    candidate.review_state = body.decision
    session.add(
        CandidateEvent(
            candidate_id=candidate_id,
            event_type="review.changed",
            payload={"domain": candidate.domain, "decision": body.decision, "reason": body.reason},
            config_version=config_row.version,
            actor_device_id=device.id,
        )
    )
    await session.flush()
    return ReviewItem.model_validate(review)


async def _event_stream(after: int) -> AsyncGenerator[str, None]:
    cursor = after
    last_keepalive = asyncio.get_running_loop().time()
    while True:
        async with session_scope() as session:
            events = (
                await session.execute(
                    select(CandidateEvent, EventReadReceipt.event_id)
                    .outerjoin(
                        EventReadReceipt,
                        EventReadReceipt.event_id == CandidateEvent.id,
                    )
                    .where(CandidateEvent.id > cursor)
                    .order_by(CandidateEvent.id)
                    .limit(100)
                )
            ).all()
        if events:
            for event, read_event_id in events:
                cursor = event.id
                payload = EventItem(
                    id=event.id,
                    candidate_id=event.candidate_id,
                    event_type=event.event_type,
                    payload=event.payload,
                    created_at=event.created_at,
                    config_version=event.config_version,
                    read=read_event_id is not None,
                ).model_dump(mode="json")
                yield f"id: {event.id}\nevent: {event.event_type}\ndata: {json.dumps(payload)}\n\n"
            last_keepalive = asyncio.get_running_loop().time()
        elif asyncio.get_running_loop().time() - last_keepalive >= settings.event_keepalive_seconds:
            yield ": keepalive\n\n"
            last_keepalive = asyncio.get_running_loop().time()
        await asyncio.sleep(settings.event_poll_interval_seconds)


@router.get("/events")
async def events(
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    _device: DeviceIdentity = Depends(require_device),
) -> StreamingResponse:
    if last_event_id:
        try:
            after = max(after, int(last_event_id))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Last-Event-ID must be numeric") from exc
    return StreamingResponse(
        _event_stream(after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/events/{event_id}/read", response_model=EventItem)
async def mark_event_read(
    event_id: int,
    device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> EventItem:
    event = await session.get(CandidateEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    await session.execute(
        insert(EventReadReceipt)
        .values(event_id=event_id, device_id=device.id)
        .on_conflict_do_nothing(index_elements=[EventReadReceipt.event_id])
    )
    return EventItem(
        id=event.id,
        candidate_id=event.candidate_id,
        event_type=event.event_type,
        payload=event.payload,
        created_at=event.created_at,
        config_version=event.config_version,
        read=True,
    )


@router.get("/jobs/{job_id}", response_model=JobItem)
async def job_detail(
    job_id: str,
    _device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> JobItem:
    job = await session.get(OperatorJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobItem.model_validate(job)


@router.post("/jobs", response_model=JobItem, status_code=201)
async def create_job(
    body: JobCreate,
    device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> JobItem:
    if body.kind not in SAFE_JOB_KINDS:
        raise HTTPException(status_code=422, detail="unsupported job kind")
    config_row, _config = await get_active_config(session)
    active_key = f"{body.kind}:{body.idempotency_key}"
    existing = (
        await session.execute(select(OperatorJob).where(OperatorJob.active_key == active_key))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail={"message": "job already active", "id": existing.id})
    job = OperatorJob(
        id=new_job_id(),
        kind=body.kind,
        state="queued",
        payload=body.payload,
        idempotency_key=body.idempotency_key,
        active_key=active_key,
        created_by_device_id=device.id,
        config_version=config_row.version,
    )
    session.add(job)
    session.add(
        CandidateEvent(
            event_type="job.queued",
            payload={"id": job.id, "kind": job.kind, "state": job.state},
            config_version=config_row.version,
            actor_device_id=device.id,
        )
    )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="equivalent job already active") from exc
    return JobItem.model_validate(job)


@router.get("/workers", response_model=list[WorkerItem])
async def workers(
    _device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> list[WorkerItem]:
    rows = (
        (await session.execute(select(WorkerHeartbeat).order_by(WorkerHeartbeat.worker_name)))
        .scalars()
        .all()
    )
    return [
        WorkerItem(
            worker_name=row.worker_name,
            state=row.state,
            job_id=row.job_id,
            observed_at=row.observed_at,
            details=row.details or {},
        )
        for row in rows
    ]


@router.get("/runs", response_model=list[RunItemV1])
async def runs(
    limit: int = Query(default=50, ge=1, le=200),
    _device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> list[RunItemV1]:
    discoveries = (
        (
            await session.execute(
                select(DiscoveryRun).order_by(DiscoveryRun.started_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    crawls = (
        (
            await session.execute(select(CrawlRun).order_by(CrawlRun.started_at.desc()).limit(limit))
        )
        .scalars()
        .all()
    )
    result = [
        RunItemV1(
            id=f"discovery:{row.id}",
            kind="discovery",
            source=row.source,
            state=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            metrics=row.metrics or {},
            error=row.error,
        )
        for row in discoveries
    ]
    result.extend(
        RunItemV1(
            id=f"crawl:{row.id}",
            kind="crawl",
            source=f"seed:{row.seed_id}",
            state=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            metrics={
                **(row.metrics or {}),
                "pages_fetched": row.pages_fetched,
                "links_observed": row.links_observed,
            },
            error=row.error,
        )
        for row in crawls
    )
    return sorted(result, key=lambda row: row.started_at, reverse=True)[:limit]


def _config_item(
    row: EngineConfigVersion, *, parent: dict[str, Any] | None = None
) -> ConfigVersionItem:
    return ConfigVersionItem(
        version=row.version,
        created_at=row.created_at,
        parent_version=row.parent_version,
        config=row.config_json,
        notes=row.notes,
        is_active=row.is_active,
        activated_at=row.activated_at,
        diff=config_diff(parent or {}, row.config_json),
    )


@router.get("/config/versions", response_model=list[ConfigVersionItem])
async def config_versions(
    _device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> list[ConfigVersionItem]:
    rows = (
        (
            await session.execute(
                select(EngineConfigVersion).order_by(EngineConfigVersion.version.desc()).limit(50)
            )
        )
        .scalars()
        .all()
    )
    by_version = {row.version: row.config_json for row in rows}
    return [
        _config_item(row, parent=by_version.get(row.parent_version) if row.parent_version else None)
        for row in rows
    ]


@router.post("/config/versions", response_model=ConfigVersionItem, status_code=201)
async def create_config_version(
    body: ConfigCreate,
    device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> ConfigVersionItem:
    validated = EngineConfig.model_validate(body.config)
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('xd-engine-config'))"))
    parent, _active = await get_active_config(session)
    next_version = int(
        (
            await session.execute(select(func.coalesce(func.max(EngineConfigVersion.version), 0)))
        ).scalar_one()
    ) + 1
    row = EngineConfigVersion(
        version=next_version,
        created_by_device_id=device.id,
        parent_version=parent.version,
        config_json=validated.model_dump(mode="json"),
        notes=body.notes,
        is_active=False,
    )
    session.add(row)
    session.add(
        CandidateEvent(
            event_type="config.created",
            payload={"version": next_version, "parent": parent.version},
            config_version=next_version,
            actor_device_id=device.id,
        )
    )
    await session.flush()
    return _config_item(row, parent=parent.config_json)


@router.post("/config/versions/{version}/activate", response_model=ConfigVersionItem)
async def activate_config_version(
    version: int,
    device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> ConfigVersionItem:
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('xd-engine-config'))"))
    row = await session.get(EngineConfigVersion, version)
    if row is None:
        raise HTTPException(status_code=404, detail="configuration version not found")
    EngineConfig.model_validate(row.config_json)
    previous, _active = await get_active_config(session)
    await session.execute(
        update(EngineConfigVersion)
        .where(EngineConfigVersion.is_active.is_(True))
        .values(is_active=False)
    )
    row.is_active = True
    row.activated_at = dt.datetime.now(dt.UTC)
    session.add(
        CandidateEvent(
            event_type="config.activated",
            payload={"version": version, "previous": previous.version},
            config_version=version,
            actor_device_id=device.id,
        )
    )
    return _config_item(row, parent=previous.config_json)


@router.post("/pairing/complete", response_model=PairingResult)
async def pairing_complete(
    body: PairingComplete,
    session: AsyncSession = Depends(v1_session),
) -> PairingResult:
    try:
        device, token = await complete_pairing(
            session, code=body.code, device_name=body.device_name
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    session.add(
        CandidateEvent(
            event_type="device.paired",
            payload={"device_id": device.id, "device_name": device.device_name},
            actor_device_id=device.id,
        )
    )
    return PairingResult(device_id=device.id, device_name=device.device_name, token=token)


@router.get("/devices", response_model=list[DeviceItem])
async def devices(
    _device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> list[DeviceItem]:
    rows = (
        (await session.execute(select(DeviceCredential).order_by(DeviceCredential.created_at)))
        .scalars()
        .all()
    )
    return [DeviceItem.model_validate(row) for row in rows]


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(
    device_id: int,
    device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> None:
    row = await session.get(DeviceCredential, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="device not found")
    if row.id == device.id:
        raise HTTPException(status_code=409, detail="pair another device before revoking this one")
    row.revoked_at = dt.datetime.now(dt.UTC)
    session.add(
        CandidateEvent(
            event_type="device.revoked",
            payload={"device_id": row.id, "device_name": row.device_name},
            actor_device_id=device.id,
        )
    )


@router.get("/portfolio", response_model=list[PortfolioOutcomeItem])
async def portfolio(
    _device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> list[PortfolioOutcomeItem]:
    rows = (
        (
            await session.execute(
                select(PortfolioOutcome).order_by(PortfolioOutcome.occurred_at.desc()).limit(500)
            )
        )
        .scalars()
        .all()
    )
    return [PortfolioOutcomeItem.model_validate(row) for row in rows]


@router.post(
    "/candidates/{candidate_id}/outcomes",
    response_model=PortfolioOutcomeItem,
    status_code=201,
)
async def record_portfolio_outcome(
    candidate_id: int,
    body: PortfolioOutcomeCreate,
    device: DeviceIdentity = Depends(require_device),
    session: AsyncSession = Depends(v1_session),
) -> PortfolioOutcomeItem:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    outcome = PortfolioOutcome(
        candidate_id=candidate_id,
        outcome=body.outcome,
        amount_micros=body.amount_micros,
        currency=body.currency.upper() if body.currency else None,
        notes=body.notes,
    )
    session.add(outcome)
    session.add(
        CandidateEvent(
            candidate_id=candidate_id,
            event_type="outcome.recorded",
            payload={"domain": candidate.domain, "outcome": body.outcome},
            actor_device_id=device.id,
        )
    )
    await session.flush()
    return PortfolioOutcomeItem.model_validate(outcome)
