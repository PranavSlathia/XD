from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dh.db.models import (
    Candidate,
    CandidateEvent,
    EngineConfigVersion,
    GateResult,
    LaneAssessment,
    LinkObservation,
    RegistrarQuote,
    SourcePage,
)
from dh.engine.configuration import EngineConfig, get_active_config
from dh.lanes.authority import AuthorityLink, AuthorityScreenInput, screen_authority
from dh.lanes.gates import LANE_GATES, SHARED_GATES
from dh.lanes.name import screen_name
from dh.lanes.types import AssessmentState, GateState, Lane


async def _upsert_assessment(
    session: AsyncSession,
    *,
    candidate: Candidate,
    config_row: EngineConfigVersion,
    lane: Lane,
    state: AssessmentState,
    screen_passed: bool,
    lane_score: float | None,
    model_version: str,
    name_subtype: str | None,
    signals: dict[str, object],
    reasons: Sequence[str],
    missing_evidence: Sequence[str],
) -> tuple[LaneAssessment, bool]:
    row = (
        await session.execute(
            select(LaneAssessment).where(
                LaneAssessment.candidate_id == candidate.id,
                LaneAssessment.lane == lane.value,
                LaneAssessment.config_version == config_row.version,
            )
        )
    ).scalar_one_or_none()
    newly_promoted = False
    if row is None:
        row = LaneAssessment(
            candidate_id=candidate.id,
            lane=lane.value,
            state=state.value,
            screen_passed=screen_passed,
            lane_score=lane_score,
            model_version=model_version,
            config_version=config_row.version,
        )
        session.add(row)
        newly_promoted = screen_passed
    else:
        newly_promoted = screen_passed and not row.screen_passed
    row.state = state.value
    row.screen_passed = screen_passed
    row.lane_score = lane_score
    row.model_version = model_version
    row.name_subtype = name_subtype
    row.computed_at = dt.datetime.now(dt.UTC)
    row.signals = signals
    row.reasons = list(reasons)
    row.missing_evidence = list(missing_evidence)
    return row, newly_promoted


async def _set_gate(
    session: AsyncSession,
    *,
    candidate_id: int,
    config_version: int,
    lane: str,
    key: str,
    state: GateState,
    fatal: bool = False,
    details: str | None = None,
    evidence_refs: Sequence[str] = (),
) -> GateResult:
    row = (
        await session.execute(
            select(GateResult).where(
                GateResult.candidate_id == candidate_id,
                GateResult.config_version == config_version,
                GateResult.lane == lane,
                GateResult.gate_key == key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = GateResult(
            candidate_id=candidate_id,
            config_version=config_version,
            lane=lane,
            gate_key=key,
            state=state.value,
        )
        session.add(row)
    changed = row.state != state.value or row.fatal != fatal
    row.state = state.value
    row.fatal = fatal
    row.details = details
    row.evidence_refs = list(evidence_refs)
    row.evaluated_at = dt.datetime.now(dt.UTC)
    if changed:
        session.add(
            CandidateEvent(
                candidate_id=candidate_id,
                event_type="gate.changed",
                payload={"lane": lane, "gate": key, "state": state.value, "fatal": fatal},
                config_version=config_version,
            )
        )
    return row


async def _ensure_pending_gates(
    session: AsyncSession,
    *,
    candidate_id: int,
    config_version: int,
    lane: Lane,
) -> None:
    existing = set(
        (
            await session.execute(
                select(GateResult.lane, GateResult.gate_key).where(
                    GateResult.candidate_id == candidate_id,
                    GateResult.config_version == config_version,
                )
            )
        ).all()
    )
    for key in sorted(SHARED_GATES):
        if ("shared", key) in existing:
            continue
        await _set_gate(
            session,
            candidate_id=candidate_id,
            config_version=config_version,
            lane="shared",
            key=key,
            state=GateState.PENDING,
        )
    for key in sorted(LANE_GATES[lane]):
        if (lane.value, key) in existing:
            continue
        await _set_gate(
            session,
            candidate_id=candidate_id,
            config_version=config_version,
            lane=lane.value,
            key=key,
            state=GateState.PENDING,
        )


async def _apply_quote_gates(
    session: AsyncSession,
    *,
    candidate_id: int,
    config_version: int,
) -> None:
    quote = (
        await session.execute(
            select(RegistrarQuote)
            .where(RegistrarQuote.candidate_id == candidate_id)
            .order_by(RegistrarQuote.observed_at.desc(), RegistrarQuote.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if quote is None:
        return
    now = dt.datetime.now(dt.UTC)
    stale = quote.expires_at is None or quote.expires_at <= now
    availability_state = GateState.PENDING
    availability_fatal = False
    if not stale and quote.availability_status == "available":
        availability_state = GateState.PASSED
    elif not stale and quote.availability_status == "unavailable":
        availability_state = GateState.FAIL
        availability_fatal = True
    await _set_gate(
        session,
        candidate_id=candidate_id,
        config_version=config_version,
        lane="shared",
        key="availability_authoritative",
        state=availability_state,
        fatal=availability_fatal,
        details="latest authoritative registrar quote",
        evidence_refs=(f"registrar_quote:{quote.id}",),
    )

    price_state = GateState.PENDING
    price_fatal = False
    if not stale and quote.price_class == "normal":
        price_state = GateState.PASSED
    elif not stale and quote.price_class in {"premium", "auction", "aftermarket"}:
        price_state = GateState.FAIL
        price_fatal = True
    await _set_gate(
        session,
        candidate_id=candidate_id,
        config_version=config_version,
        lane="shared",
        key="standard_registration_price",
        state=price_state,
        fatal=price_fatal,
        details="latest registrar price classification",
        evidence_refs=(f"registrar_quote:{quote.id}",),
    )


async def _authority_links(session: AsyncSession, candidate_id: int) -> tuple[AuthorityLink, ...]:
    rows = (
        await session.execute(
            select(LinkObservation, SourcePage)
            .join(SourcePage, SourcePage.id == LinkObservation.source_page_id)
            .where(LinkObservation.candidate_id == candidate_id)
            .order_by(LinkObservation.last_seen.desc())
            .limit(500)
        )
    ).all()
    return tuple(
        AuthorityLink(
            source_domain=page.host,
            source_url=page.url,
            anchor_text=observation.anchor_text,
            context_text=observation.context_text,
            live=bool(observation.currently_live),
            editorial=bool(observation.is_editorial),
            followable="nofollow" not in (observation.rel_flags or []),
            relevant=bool(page.topic),
            independent=page.host != observation.target_domain,
            technical=observation.semantic_location in {"head", "script", "canonical"},
        )
        for observation, page in rows
    )


async def assess_candidate(
    session: AsyncSession,
    candidate: Candidate,
    *,
    config_row: EngineConfigVersion | None = None,
    config: EngineConfig | None = None,
) -> set[Lane]:
    if config_row is None or config is None:
        config_row, config = await get_active_config(session)
    promoted_lanes: set[Lane] = set()
    newly_promoted_lanes: set[Lane] = set()

    name_result = screen_name(candidate.domain, minimum_score=config.name.screen_min_score)
    _name_row, name_new = await _upsert_assessment(
        session,
        candidate=candidate,
        config_row=config_row,
        lane=Lane.NAME,
        state=AssessmentState.RESEARCH if name_result.screen_passed else AssessmentState.REJECTED,
        screen_passed=name_result.screen_passed,
        lane_score=name_result.score,
        model_version=name_result.model_version,
        name_subtype=name_result.subtype.value if name_result.subtype else None,
        signals={"tokens": list(name_result.tokens)},
        reasons=name_result.reasons,
        missing_evidence=(
            ("domain-specific comparable sales", "buyer thesis", "rights clearance")
            if name_result.screen_passed
            else name_result.failures
        ),
    )
    if name_result.screen_passed:
        promoted_lanes.add(Lane.NAME)
        if name_new:
            newly_promoted_lanes.add(Lane.NAME)
        await _ensure_pending_gates(
            session,
            candidate_id=candidate.id,
            config_version=config_row.version,
            lane=Lane.NAME,
        )
        await _set_gate(
            session,
            candidate_id=candidate.id,
            config_version=config_row.version,
            lane=Lane.NAME.value,
            key="name_quality",
            state=GateState.PASSED,
            details=f"{name_result.subtype.value if name_result.subtype else 'unknown'} screen passed",
            evidence_refs=(f"lane_assessment:{_name_row.id}",) if _name_row.id else (),
        )

    links = await _authority_links(session, candidate.id)
    authority_result = screen_authority(
        AuthorityScreenInput(
            domain=candidate.domain,
            referring_domains=candidate.referring_domains,
            open_pagerank=float(candidate.open_pagerank) if candidate.open_pagerank else None,
            observed_links=links,
            minimum_referring_domains=config.authority.prefilter_min_referring_domains,
        )
    )
    _authority_row, authority_new = await _upsert_assessment(
        session,
        candidate=candidate,
        config_row=config_row,
        lane=Lane.AUTHORITY,
        state=(
            AssessmentState.RESEARCH
            if authority_result.screen_passed
            else AssessmentState.REJECTED
        ),
        screen_passed=authority_result.screen_passed,
        lane_score=authority_result.score,
        model_version=authority_result.model_version,
        name_subtype=None,
        signals={
            "provider_referring_domains": candidate.referring_domains,
            "verified_independent_domains": authority_result.verified_independent_domains,
        },
        reasons=authority_result.reasons,
        missing_evidence=authority_result.missing_evidence,
    )
    if authority_result.screen_passed:
        promoted_lanes.add(Lane.AUTHORITY)
        if authority_new:
            newly_promoted_lanes.add(Lane.AUTHORITY)
        await _ensure_pending_gates(
            session,
            candidate_id=candidate.id,
            config_version=config_row.version,
            lane=Lane.AUTHORITY,
        )
        if authority_result.verified_independent_domains > 0:
            await _set_gate(
                session,
                candidate_id=candidate.id,
                config_version=config_row.version,
                lane=Lane.AUTHORITY.value,
                key="verified_referring_pages",
                state=GateState.PASSED,
                details="direct live editorial referring pages were validated",
            )
        # The rubric remains pending until a labelled evaluation explicitly
        # enables it in a versioned configuration.
        if config.authority.ready_thresholds_enabled:
            await _set_gate(
                session,
                candidate_id=candidate.id,
                config_version=config_row.version,
                lane=Lane.AUTHORITY.value,
                key="authority_rubric",
                state=GateState.PASSED,
                details="versioned labelled authority rubric enabled",
            )

    if promoted_lanes:
        if candidate.promoted_at is None:
            candidate.promoted_at = dt.datetime.now(dt.UTC)
            candidate.review_state = "research"
        await _apply_quote_gates(
            session,
            candidate_id=candidate.id,
            config_version=config_row.version,
        )
    for lane in newly_promoted_lanes:
        session.add(
            CandidateEvent(
                candidate_id=candidate.id,
                event_type="candidate.promoted",
                payload={"domain": candidate.domain, "lane": lane.value},
                config_version=config_row.version,
            )
        )
    return promoted_lanes


async def recompute_candidates(
    session: AsyncSession, *, limit: int = 1_000, candidate_id: int | None = None
) -> int:
    config_row, config = await get_active_config(session)
    stmt = select(Candidate).order_by(Candidate.last_observed.desc(), Candidate.id).limit(limit)
    if candidate_id is not None:
        stmt = select(Candidate).where(Candidate.id == candidate_id)
    rows = (await session.execute(stmt)).scalars().all()
    for candidate in rows:
        await assess_candidate(session, candidate, config_row=config_row, config=config)
    return len(rows)
