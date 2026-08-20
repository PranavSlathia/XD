from __future__ import annotations

import datetime as dt
import hashlib
import os
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dh.config import settings
from dh.db.engine import session_scope
from dh.db.models import (
    Candidate,
    CandidateEvent,
    LinkObservation,
    OperatorJob,
    SourcePage,
    WorkerHeartbeat,
)
from dh.engine.assessments import assess_candidate, recompute_candidates
from dh.engine.dossiers import generate_dossiers
from dh.providers.budget import ProviderBudgetExhaustedError
from dh.providers.dataforseo import DataForSEOBacklinkProvider, DataForSEOError
from dh.sources.content.crawler import run_seed
from dh.sources.content.validator import validate_candidate_links
from dh.workers.inventory import run_once as run_inventory
from dh.workers.rdap import run_batch as run_rdap_batch
from dh.workers.registrar import run_batch as run_registrar_batch
from dh.workers.wayback import refresh_candidate as refresh_wayback_candidate
from dh.workers.wayback import run_batch as run_wayback_batch

SAFE_JOB_KINDS = frozenset(
    {
        "inventory_scan",
        "content_crawl",
        "availability_refresh",
        "backlink_validate",
        "wayback_refresh",
        "recompute_assessments",
        "generate_dossier",
    }
)


class PartialJobError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    id: str
    kind: str
    payload: dict[str, Any]
    idempotency_key: str
    config_version: int
    created_by_device_id: int | None


def new_job_id() -> str:
    return str(uuid.uuid4())


def should_throttle_load(load_15m: float, max_load_15m: float) -> bool:
    return load_15m >= max_load_15m


async def claim_next_job(worker_name: str) -> ClaimedJob | None:
    async with session_scope() as session:
        try:
            load_15m = os.getloadavg()[2]
        except OSError:
            load_15m = 0.0
        if should_throttle_load(load_15m, settings.operator_max_load_15m):
            await _heartbeat(
                session,
                worker_name,
                "throttled",
                None,
                {
                    "load_15m": round(load_15m, 2),
                    "resume_below": settings.operator_max_load_15m,
                },
            )
            return None
        job = (
            await session.execute(
                select(OperatorJob)
                .where(OperatorJob.state == "queued")
                .order_by(OperatorJob.created_at, OperatorJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).scalar_one_or_none()
        if job is None:
            await _heartbeat(session, worker_name, "idle", None, {})
            return None
        job.state = "running"
        job.started_at = dt.datetime.now(dt.UTC)
        job.claimed_by = worker_name
        session.add(
            CandidateEvent(
                event_type="job.running",
                payload={"id": job.id, "kind": job.kind, "state": job.state},
                config_version=job.config_version,
                actor_device_id=job.created_by_device_id,
            )
        )
        await _heartbeat(session, worker_name, "running", job.id, {"kind": job.kind})
        return ClaimedJob(
            id=job.id,
            kind=job.kind,
            payload=job.payload,
            idempotency_key=job.idempotency_key,
            config_version=job.config_version,
            created_by_device_id=job.created_by_device_id,
        )


async def _heartbeat(
    session: AsyncSession,
    worker_name: str,
    state: str,
    job_id: str | None,
    details: dict[str, Any],
) -> None:
    row = await session.get(WorkerHeartbeat, worker_name)
    if row is None:
        row = WorkerHeartbeat(worker_name=worker_name, state=state)
        session.add(row)
    row.state = state
    row.job_id = job_id
    row.observed_at = dt.datetime.now(dt.UTC)
    row.details = details


async def finish_job(
    job_id: str,
    *,
    state: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    async with session_scope() as session:
        job = await session.get(OperatorJob, job_id)
        if job is None:
            return
        job.state = state
        job.result = result
        job.error = error[:4000] if error else None
        job.finished_at = dt.datetime.now(dt.UTC)
        job.active_key = None
        session.add(
            CandidateEvent(
                event_type=f"job.{state}",
                payload={"id": job.id, "kind": job.kind, "state": state},
                config_version=job.config_version,
                actor_device_id=job.created_by_device_id,
            )
        )
        if job.claimed_by:
            await _heartbeat(session, job.claimed_by, "idle", None, {"last_job": job.id})


def _payload_int(payload: dict[str, Any], key: str, *, default: int | None = None) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"job payload requires integer {key}")
    return value


async def _inventory(_job: ClaimedJob) -> dict[str, Any]:
    return {"persisted": await run_inventory(detail_concurrency=2)}


async def _content(job: ClaimedJob) -> dict[str, Any]:
    return await run_seed(_payload_int(job.payload, "seed_id"), operator_job_id=job.id)


async def _availability(job: ClaimedJob) -> dict[str, Any]:
    batch_size = min(100, max(1, _payload_int(job.payload, "batch_size", default=10)))
    rdap_processed = await run_rdap_batch(batch_size=batch_size, concurrency=2)
    if not settings.porkbun_api_key or not settings.porkbun_secret_api_key:
        raise PartialJobError(
            f"RDAP refreshed {rdap_processed} candidates; registrar credentials are missing, "
            "so authoritative availability and price evidence remain pending"
        )
    quoted = await run_registrar_batch(batch_size=batch_size)
    return {"rdap_processed": rdap_processed, "registrar_quotes": quoted}


async def _wayback(job: ClaimedJob) -> dict[str, Any]:
    candidate_id = job.payload.get("candidate_id")
    if candidate_id is not None:
        if isinstance(candidate_id, bool) or not isinstance(candidate_id, int):
            raise ValueError("candidate_id must be an integer")
        return {"processed": await refresh_wayback_candidate(candidate_id)}
    batch_size = min(20, max(1, _payload_int(job.payload, "batch_size", default=5)))
    return {
        "processed": await run_wayback_batch(
            batch_size=batch_size, top_n=200, concurrency=1
        )
    }


async def _recompute(job: ClaimedJob) -> dict[str, Any]:
    candidate_id = job.payload.get("candidate_id")
    if candidate_id is not None and (isinstance(candidate_id, bool) or not isinstance(candidate_id, int)):
        raise ValueError("candidate_id must be an integer")
    limit = min(5_000, max(1, _payload_int(job.payload, "limit", default=1_000)))
    async with session_scope() as session:
        processed = await recompute_candidates(
            session,
            limit=limit,
            candidate_id=candidate_id,
        )
    return {"processed": processed}


async def _dossier(job: ClaimedJob) -> dict[str, Any]:
    async with session_scope() as session:
        generated = await generate_dossiers(
            session, _payload_int(job.payload, "candidate_id")
        )
    return {"generated": generated}


async def _backlinks(job: ClaimedJob) -> dict[str, Any]:
    candidate_id = _payload_int(job.payload, "candidate_id")
    try:
        provider = DataForSEOBacklinkProvider(candidate_id=candidate_id)
    except DataForSEOError as exc:
        raise PartialJobError(f"{exc}; backlink evidence remains pending") from exc
    try:
        async with session_scope() as session:
            candidate = await session.get(Candidate, candidate_id)
            if candidate is None:
                raise ValueError("candidate not found")
            summary = await provider.summary(session, candidate.domain)
            records = await provider.backlinks(session, candidate.domain, limit=100)
            candidate.referring_domains = summary.referring_domains
            candidate.authority_source = provider.name
            candidate.authority_observed_at = dt.datetime.now(dt.UTC)
            for record in records:
                page = (
                    await session.execute(
                        select(SourcePage).where(SourcePage.url == record.source_url)
                    )
                ).scalar_one_or_none()
                if page is None:
                    page = SourcePage(
                        url=record.source_url,
                        host=record.source_domain,
                        source_kind="dataforseo_backlinks",
                    )
                    session.add(page)
                    await session.flush()
                digest = hashlib.sha256(record.target_url.encode()).digest()
                observation = (
                    await session.execute(
                        select(LinkObservation).where(
                            LinkObservation.source_page_id == page.id,
                            LinkObservation.target_url_hash == digest,
                        )
                    )
                ).scalar_one_or_none()
                is_new_observation = observation is None
                if observation is None:
                    observation = LinkObservation(
                        source_page_id=page.id,
                        candidate_id=candidate.id,
                        target_url=record.target_url,
                        target_url_hash=digest,
                        target_domain=candidate.domain,
                    )
                    session.add(observation)
                if is_new_observation:
                    observation.anchor_text = record.anchor
                    observation.context_text = " ".join(
                        part for part in (record.text_before, record.text_after) if part
                    ) or None
                    observation.semantic_location = record.semantic_location
                    observation.rel_flags = [] if record.dofollow else ["nofollow"]
                    observation.is_editorial = record.semantic_location in {
                        "article",
                        "section",
                        "main",
                    }
                    # Provider data is a prefilter. A direct fetch must set
                    # currently_live before this can satisfy a readiness gate.
                    observation.currently_live = None
        validation = await validate_candidate_links(candidate_id, limit=min(20, len(records)))
        async with session_scope() as session:
            candidate = await session.get(Candidate, candidate_id)
            if candidate is None:
                raise ValueError("candidate not found")
            await assess_candidate(session, candidate)
        return {
            "referring_domains": summary.referring_domains,
            "provider_records": len(records),
            "direct_validation": validation,
        }
    except (ProviderBudgetExhaustedError, DataForSEOError) as exc:
        raise PartialJobError(f"{exc}; backlink evidence remains pending") from exc
    finally:
        await provider.aclose()


Handler = Callable[[ClaimedJob], Awaitable[dict[str, Any]]]
HANDLERS: dict[str, Handler] = {
    "inventory_scan": _inventory,
    "content_crawl": _content,
    "availability_refresh": _availability,
    "backlink_validate": _backlinks,
    "wayback_refresh": _wayback,
    "recompute_assessments": _recompute,
    "generate_dossier": _dossier,
}


async def execute_job(job: ClaimedJob) -> dict[str, Any]:
    handler = HANDLERS.get(job.kind)
    if handler is None or job.kind not in SAFE_JOB_KINDS:
        raise ValueError("unsupported operator job kind")
    return await handler(job)
