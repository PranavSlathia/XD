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
from dh.db.models import WaybackSnapshot
from dh.logging import configure_logging, log
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

    Ranks by MAX(sources.authority) across all source_mentions; takes top_n
    overall, then slices the first batch_size from that pool that need work.
    """
    sql = text(
        """
        WITH ranked AS (
            SELECT c.id, c.domain, COALESCE(MAX(s.authority), 0) AS auth
            FROM candidates c
            LEFT JOIN source_mentions sm ON sm.candidate_id = c.id
            LEFT JOIN sources s ON s.id = sm.source_id
            GROUP BY c.id, c.domain
            ORDER BY auth DESC NULLS LAST
            LIMIT :top_n
        )
        SELECT r.id, r.domain
        FROM ranked r
        WHERE NOT EXISTS (
            SELECT 1 FROM wayback_snapshots w
            WHERE w.candidate_id = r.id
              AND w.observed_at > now() - (:stale || ' days')::interval
        )
        LIMIT :lim
        """
    )
    res = await session.execute(
        sql, {"top_n": top_n, "stale": str(STALE_AFTER_DAYS), "lim": batch_size}
    )
    return [(row[0], row[1]) for row in res.all()]


async def _persist(session: AsyncSession, candidate_id: int, cdx: CdxSummary) -> None:
    if cdx.capture_count == 0:
        return
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
            },
        )
    )


async def run_batch(*, batch_size: int, top_n: int, concurrency: int = 4) -> int:
    async with session_scope() as session:
        rows = await _claim_batch(session, batch_size=batch_size, top_n=top_n)
    if not rows:
        return 0

    sem = asyncio.Semaphore(concurrency)

    async def _one(cid: int, domain: str) -> tuple[int, CdxSummary]:
        async with sem:
            try:
                return cid, await fetch_cdx(domain)
            except Exception as e:
                log.warning("worker.wayback.error", domain=domain, error=str(e))
                return cid, CdxSummary(domain=domain)

    results = await asyncio.gather(*(_one(cid, d) for cid, d in rows))
    async with session_scope() as session:
        for cid, cdx in results:
            await _persist(session, cid, cdx)

    log.info("worker.wayback.batch.done", processed=len(results))
    return len(results)


async def _run(shutdown: asyncio.Event, interval_seconds: float) -> None:
    while not shutdown.is_set():
        try:
            await run_batch(
                batch_size=settings.wayback_batch_size, top_n=settings.wayback_top_n
            )
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
    from dh.observability import setup_sentry

    setup_sentry(service="worker-wayback")
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
