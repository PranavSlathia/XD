"""Wayback CDX enrichment worker.

Polls candidates that lack a fresh wayback_snapshots row (>30 days old), ranked
by max source authority. Fetches CDX summary and writes a snapshot row.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import signal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dh.config import settings
from dh.db.engine import session_scope
from dh.db.models import Candidate, WaybackSnapshot
from dh.logging import configure_logging, log
from dh.opportunity import MODEL_VERSION
from dh.sources.wayback.cdx import CdxSummary, fetch_cdx


def _ts_to_date(ts: str | None) -> dt.date | None:
    """Parse a CDX YYYYMMDDHHMMSS timestamp into a date (or None)."""
    if not ts or len(ts) < 8:
        return None
    try:
        return dt.date(int(ts[0:4]), int(ts[4:6]), int(ts[6:8]))
    except ValueError:
        return None


STALE_AFTER_DAYS = 30


async def _claim_batch(
    session: AsyncSession, *, batch_size: int, top_n: int
) -> list[tuple[int, str]]:
    """Return (id, domain) pairs needing a fresh Wayback summary.

    Only real, currently active acquisition inventory is eligible. Research
    candidates are checked first, then the remaining authority-ranked pool.
    """
    sql = text(
        """
        WITH ranked AS (
            SELECT c.id, c.domain, oa.verdict, oa.overall_score
            FROM candidates c
            JOIN opportunity_assessments oa
              ON oa.candidate_id = c.id
             AND oa.model_version = :model_version
            WHERE c.open_pagerank >= :opr_floor
              AND COALESCE((
                  SELECT o.decision
                  FROM outcomes o
                  WHERE o.candidate_id = c.id
                  ORDER BY o.decided_at DESC, o.id DESC
                  LIMIT 1
              ), '') NOT IN ('passed', 'bought', 'lost_to_other')
              AND EXISTS (
                  SELECT 1 FROM marketplace_listings ml
                  WHERE ml.candidate_id = c.id
                    AND ml.listing_status = 'active'
                    AND ml.drop_date >= current_date - 1
              )
            ORDER BY
                CASE oa.verdict WHEN 'research' THEN 0 WHEN 'observe' THEN 1 ELSE 2 END,
                oa.overall_score DESC,
                c.authority_rank ASC NULLS LAST
            LIMIT :top_n
        )
        SELECT r.id, r.domain
        FROM ranked r
        WHERE NOT EXISTS (
            SELECT 1 FROM wayback_snapshots w
            WHERE w.candidate_id = r.id
              AND w.observed_at > now() - (:stale || ' days')::interval
        )
        ORDER BY
            CASE r.verdict WHEN 'research' THEN 0 WHEN 'observe' THEN 1 ELSE 2 END,
            r.overall_score DESC
        LIMIT :lim
        """
    )
    res = await session.execute(
        sql,
        {
            "top_n": top_n,
            "stale": str(STALE_AFTER_DAYS),
            "lim": batch_size,
            "model_version": MODEL_VERSION,
            "opr_floor": settings.inventory_min_opr,
        },
    )
    return [(row[0], row[1]) for row in res.all()]


async def _persist(session: AsyncSession, candidate_id: int, cdx: CdxSummary) -> None:
    session.add(
        WaybackSnapshot(
            candidate_id=candidate_id,
            first_capture=_ts_to_date(cdx.first_capture),
            last_capture=_ts_to_date(cdx.last_capture),
            capture_count=cdx.capture_count,
            cdx_summary={
                "first_capture_ts": cdx.first_capture,
                "last_capture_ts": cdx.last_capture,
                "entries_sampled": len(cdx.entries),
                "metric": "unique_200_status_urls",
            },
        )
    )
    cand = await session.get(Candidate, candidate_id)
    if cand is not None:
        cand.score_version = None


async def run_batch(*, batch_size: int, top_n: int, concurrency: int = 2) -> int:
    async with session_scope() as session:
        rows = await _claim_batch(session, batch_size=batch_size, top_n=top_n)
    if not rows:
        return 0

    sem = asyncio.Semaphore(concurrency)

    async def _one(cid: int, domain: str) -> tuple[int, CdxSummary | None]:
        async with sem:
            try:
                return cid, await fetch_cdx(domain)
            except Exception as e:
                log.warning("worker.wayback.error", domain=domain, error=str(e))
                return cid, None

    results = await asyncio.gather(*(_one(cid, d) for cid, d in rows))
    successful = [(cid, cdx) for cid, cdx in results if cdx is not None]
    if successful:
        async with session_scope() as session:
            for cid, cdx in successful:
                await _persist(session, cid, cdx)

    log.info(
        "worker.wayback.batch.done",
        attempted=len(results),
        processed=len(successful),
        failed=len(results) - len(successful),
    )
    return len(successful)


async def _run(shutdown: asyncio.Event, interval_seconds: float) -> None:
    while not shutdown.is_set():
        try:
            await run_batch(batch_size=settings.wayback_batch_size, top_n=settings.wayback_top_n)
        except Exception as e:
            log.error("worker.wayback.batch.error", error=str(e))
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event) -> None:
    def _handler() -> None:
        log.info("worker.wayback.signal.received")
        shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            pass


async def _amain() -> None:
    shutdown = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), shutdown)
    interval = float(settings.wayback_interval_minutes) * 60.0
    log.info(
        "worker.wayback.start",
        batch_size=settings.wayback_batch_size,
        top_n=settings.wayback_top_n,
    )
    await _run(shutdown, interval)
    log.info("worker.wayback.exit")


def main() -> None:
    configure_logging()
    from dh.observability import setup_sentry, setup_tracing

    setup_sentry(service="worker-wayback")
    setup_tracing(service="wayback")
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
