"""RDAP enrichment worker.

Polls ``candidates`` lacking a recent authoritative ``availability_checks`` row,
runs the RDAP waterfall, persists results to ``availability_checks`` and
``rdap_snapshots``, and updates the candidate's current_status/confidence.

Idempotent: a candidate whose latest authoritative check is fresher than
``stale_after_days`` is skipped.
"""
from __future__ import annotations

import asyncio
import signal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dh.config import settings
from dh.db.engine import session_scope
from dh.db.models import AvailabilityCheck, Candidate, RdapSnapshot
from dh.logging import configure_logging, log
from dh.sources.rdap.client import AvailabilityResult, check_availability

STALE_AFTER_DAYS = 7


async def _claim_batch(session: AsyncSession, *, batch_size: int) -> list[tuple[int, str]]:
    """Return (id, domain) pairs needing a fresh authoritative check."""
    sql = text(
        """
        SELECT c.id, c.domain
        FROM candidates c
        WHERE NOT EXISTS (
            SELECT 1 FROM availability_checks a
            WHERE a.candidate_id = c.id
              AND a.is_authoritative = true
              AND a.observed_at > now() - (:stale || ' days')::interval
        )
        ORDER BY c.last_observed DESC NULLS LAST
        LIMIT :lim
        """
    )
    res = await session.execute(sql, {"stale": STALE_AFTER_DAYS, "lim": batch_size})
    return [(row[0], row[1]) for row in res.all()]


async def _persist(
    session: AsyncSession, candidate_id: int, avail: AvailabilityResult
) -> None:
    session.add(
        AvailabilityCheck(
            candidate_id=candidate_id,
            source=avail.source,
            status=avail.status,
            is_authoritative=(avail.confidence == "authoritative"),
            cost_micros=avail.api_cost_micros,
            raw_response=avail.raw_response,
        )
    )
    if avail.source == "rdap" and avail.confidence != "unknown":
        rdap_server = None
        if isinstance(avail.raw_response, dict):
            v = avail.raw_response.get("rdap_server")
            if isinstance(v, str):
                rdap_server = v
        session.add(
            RdapSnapshot(
                candidate_id=candidate_id,
                rdap_server=rdap_server,
                epp_statuses=avail.epp_statuses or None,
                expiry_date=None,
                registrar=avail.registrar,
                raw_response=avail.raw_response,
            )
        )
    if avail.confidence == "authoritative":
        cand = await session.get(Candidate, candidate_id)
        if cand is not None:
            cand.current_status = avail.status
            cand.availability_confidence = avail.confidence


async def run_batch(*, batch_size: int, concurrency: int = 4) -> int:
    """Run one enrichment batch; return number of candidates processed."""
    async with session_scope() as session:
        rows = await _claim_batch(session, batch_size=batch_size)

    if not rows:
        return 0

    sem = asyncio.Semaphore(concurrency)

    async def _one(cid: int, domain: str) -> tuple[int, AvailabilityResult]:
        async with sem:
            try:
                return cid, await check_availability(domain)
            except Exception as e:
                log.warning("worker.rdap.error", domain=domain, error=str(e))
                return cid, AvailabilityResult(
                    domain=domain,
                    status="unknown",
                    confidence="unknown",
                    source="rdap",
                    raw_response={"error": str(e)},
                )

    results = await asyncio.gather(*(_one(cid, d) for cid, d in rows))
    async with session_scope() as session:
        for cid, avail in results:
            await _persist(session, cid, avail)

    log.info("worker.rdap.batch.done", processed=len(results))
    return len(results)


async def _run(shutdown: asyncio.Event, interval_seconds: float) -> None:
    while not shutdown.is_set():
        try:
            await run_batch(batch_size=settings.rdap_batch_size)
        except Exception as e:
            log.error("worker.rdap.batch.error", error=str(e))
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event) -> None:
    def _handler() -> None:
        log.info("worker.rdap.signal.received")
        shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            pass


async def _amain() -> None:
    shutdown = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), shutdown)
    interval = float(settings.rdap_interval_minutes) * 60.0
    log.info(
        "worker.rdap.start",
        batch_size=settings.rdap_batch_size,
        interval_minutes=settings.rdap_interval_minutes,
    )
    await _run(shutdown, interval)
    log.info("worker.rdap.exit")


def main() -> None:
    configure_logging()
    from dh.observability import setup_sentry

    setup_sentry(service="worker-rdap")
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
