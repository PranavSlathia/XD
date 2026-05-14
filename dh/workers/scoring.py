"""Composite-scoring worker (PRD §4.5).

Recomputes composite_score for any candidate whose ``score_version`` differs
from the current ``scoring_weights.version``. Pure-DB; no external IO.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import signal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from dh.config import settings
from dh.db.engine import session_scope
from dh.db.models import (
    AvailabilityCheck,
    Candidate,
    ClassificationRun,
    RegistrarQuote,
    ScoringWeights,
    WaybackSnapshot,
)
from dh.logging import configure_logging, log
from dh.score.composite import EnrichmentInputs, compute


async def _current_version_and_weights(
    session: AsyncSession,
) -> tuple[int | None, dict[str, float]]:
    res = await session.execute(
        select(ScoringWeights).order_by(ScoringWeights.version.desc()).limit(1)
    )
    row = res.scalar_one_or_none()
    if row is None:
        return None, {}
    weights_raw = row.weights_json or {}
    # JSONB → values can be float|int
    weights: dict[str, float] = {k: float(v) for k, v in weights_raw.items()}
    return row.version, weights


async def _claim_batch(
    session: AsyncSession, *, current_version: int, batch_size: int
) -> list[int]:
    sql = text(
        """
        SELECT id FROM candidates
        WHERE score_version IS NULL OR score_version <> :v
        ORDER BY id
        LIMIT :lim
        """
    )
    res = await session.execute(sql, {"v": current_version, "lim": batch_size})
    return [row[0] for row in res.all()]


async def _gather_inputs(
    session: AsyncSession, candidate_id: int
) -> EnrichmentInputs:
    cand = await session.get(Candidate, candidate_id)
    if cand is None:
        return EnrichmentInputs()

    # mentions / source authority
    sm_rows = await session.execute(
        text(
            """
            SELECT COALESCE(MAX(s.authority), 0)::float AS max_auth,
                   COUNT(DISTINCT sm.source_id) AS distinct_sources
            FROM source_mentions sm
            LEFT JOIN sources s ON s.id = sm.source_id
            WHERE sm.candidate_id = :cid
            """
        ),
        {"cid": candidate_id},
    )
    sm_row = sm_rows.first()
    max_auth = float(sm_row[0]) if sm_row else 0.0
    distinct_sources = int(sm_row[1]) if sm_row else 0

    # latest availability_check (authoritative)
    res = await session.execute(
        select(AvailabilityCheck)
        .where(
            AvailabilityCheck.candidate_id == candidate_id,
            AvailabilityCheck.is_authoritative.is_(True),
        )
        .order_by(AvailabilityCheck.observed_at.desc())
        .limit(1)
    )
    av = res.scalar_one_or_none()
    current_status = av.status if av else cand.current_status
    availability_confidence = "authoritative" if av else cand.availability_confidence

    # latest wayback snapshot
    res = await session.execute(
        select(WaybackSnapshot)
        .where(WaybackSnapshot.candidate_id == candidate_id)
        .order_by(WaybackSnapshot.observed_at.desc())
        .limit(1)
    )
    wb = res.scalar_one_or_none()
    first_year: int | None = None
    if wb and wb.cdx_summary:
        ts = wb.cdx_summary.get("first_capture_ts")
        if isinstance(ts, str) and len(ts) >= 4 and ts[:4].isdigit():
            first_year = int(ts[:4])

    # latest classification
    res = await session.execute(
        select(ClassificationRun)
        .where(ClassificationRun.candidate_id == candidate_id)
        .order_by(ClassificationRun.observed_at.desc())
        .limit(1)
    )
    clr = res.scalar_one_or_none()
    wb_class = clr.classification if clr else None

    # latest registrar quote
    res = await session.execute(
        select(RegistrarQuote)
        .where(RegistrarQuote.candidate_id == candidate_id)
        .order_by(RegistrarQuote.observed_at.desc())
        .limit(1)
    )
    rq = res.scalar_one_or_none()
    quote_price = rq.quote_price_micros if rq else None

    return EnrichmentInputs(
        max_source_authority=max_auth,
        distinct_sources=distinct_sources,
        referring_domains=0,  # Phase 2 (Common Crawl)
        open_pagerank=0.0,    # TODO: persist OPR; for now 0
        wayback_classification=wb_class,
        wayback_first_capture_year=first_year,
        current_year=dt.datetime.now(dt.UTC).year,
        spam_flag=False,
        tm_risk_probability=0.0,  # Phase 2 (USPTO)
        reputation_flag=None,     # Phase 2
        quote_price_micros=quote_price,
        premium_ceiling_micros=settings.premium_ceiling_micros,
        current_status=current_status,
        availability_confidence=availability_confidence,
    )


async def run_batch(*, batch_size: int) -> int:
    async with session_scope() as session:
        version, weights = await _current_version_and_weights(session)
        if version is None:
            log.warning("worker.scoring.no_weights")
            return 0
        ids = await _claim_batch(session, current_version=version, batch_size=batch_size)
        if not ids:
            return 0

        for cid in ids:
            inputs = await _gather_inputs(session, cid)
            verdict = compute(inputs, weights=weights)
            cand = await session.get(Candidate, cid)
            if cand is None:
                continue
            cand.composite_score = verdict.composite
            cand.score_version = version
            cand.hard_filtered = verdict.hard_filtered
            cand.hard_filter_reason = verdict.hard_filter_reason
        return len(ids)


async def _run(shutdown: asyncio.Event, interval_seconds: float) -> None:
    while not shutdown.is_set():
        try:
            n = await run_batch(batch_size=settings.scoring_batch_size)
            log.info("worker.scoring.batch.done", processed=n)
        except Exception as e:
            log.error("worker.scoring.batch.error", error=str(e))
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event) -> None:
    def _handler() -> None:
        log.info("worker.scoring.signal.received")
        shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            pass


async def _amain() -> None:
    shutdown = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), shutdown)
    interval = float(settings.scoring_interval_seconds)
    log.info("worker.scoring.start", batch_size=settings.scoring_batch_size)
    await _run(shutdown, interval)
    log.info("worker.scoring.exit")


def main() -> None:
    configure_logging()
    from dh.observability import setup_sentry

    setup_sentry(service="worker-scoring")
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
