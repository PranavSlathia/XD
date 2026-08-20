from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dh.db.models import (
    Candidate,
    CandidateDossier,
    CandidateEvent,
    GateResult,
    LaneAssessment,
)
from dh.engine.configuration import get_active_config
from dh.lanes.gates import GateEvidence, evaluate_readiness
from dh.lanes.types import GateState, Lane


async def generate_dossiers(session: AsyncSession, candidate_id: int) -> int:
    candidate = await session.get(Candidate, candidate_id)
    if candidate is None:
        raise ValueError("candidate not found")
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
    gate_evidence = tuple(
        GateEvidence(
            lane=row.lane,
            key=row.gate_key,
            state=GateState(row.state),
            fatal=row.fatal,
        )
        for row in gates
    )
    screened_lanes = {Lane(row.lane) for row in assessments}
    readiness = evaluate_readiness(screened_lanes, gate_evidence)
    existing = (
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
    dossiers = {row.lane: row for row in existing}
    generated = 0
    completed_lanes: set[Lane] = set()
    for assessment in assessments:
        lane = Lane(assessment.lane)
        dossier = dossiers.get(lane.value)
        if dossier is None:
            dossier = CandidateDossier(
                candidate_id=candidate_id,
                lane=lane.value,
                config_version=config_row.version,
                status="research",
            )
            session.add(dossier)
        previously_complete = dossier.status == "complete"
        dossier.generated_at = dt.datetime.now(dt.UTC)
        dossier.status = "complete" if lane in readiness.ready_lanes else "research"
        dossier.thesis = (
            f"{candidate.domain} passed the independent {lane.value} screening lane. "
            "This dossier records evidence, not an appraisal or purchase instruction."
        )
        dossier.risks = [
            item for item in (*readiness.failed, *readiness.fatal_failures) if item
        ]
        dossier.evidence_summary = {
            "lane_score": float(assessment.lane_score) if assessment.lane_score is not None else None,
            "subtype": assessment.name_subtype,
            "reasons": assessment.reasons or [],
            "missing": sorted(
                item for item in readiness.pending if item.startswith(("shared:", f"{lane.value}:"))
            ),
            "signals": assessment.signals or {},
        }
        assessment.state = "qualified" if lane in readiness.ready_lanes else "research"
        if dossier.status == "complete" and not previously_complete:
            completed_lanes.add(lane)
        generated += 1
    candidate.dossier_updated_at = dt.datetime.now(dt.UTC)
    if generated:
        session.add(
            CandidateEvent(
                candidate_id=candidate_id,
                event_type=("dossier.completed" if completed_lanes else "dossier.updated"),
                payload={
                    "domain": candidate.domain,
                    "lanes": sorted(lane.value for lane in screened_lanes),
                    "completed_lanes": sorted(lane.value for lane in completed_lanes),
                },
                config_version=config_row.version,
            )
        )
    return generated
