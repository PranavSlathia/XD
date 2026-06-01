"""Registrar quote worker.

Quotes only domains that RDAP/availability marked as acquirable. The digest
requires a quote row, so unknown/premium pricing does not leak into the shortlist.
"""
from __future__ import annotations

import asyncio
import signal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dh.config import settings
from dh.db.engine import session_scope
from dh.db.models import Candidate, RegistrarQuote
from dh.logging import configure_logging, log
from dh.sources.registrar.porkbun import RegistrarQuoteResult, quote_domain

STALE_AFTER_DAYS = 1


async def _claim_batch(session: AsyncSession, *, batch_size: int) -> list[tuple[int, str]]:
    sql = text(
        """
        SELECT c.id, c.domain
        FROM candidates c
        WHERE c.availability_confidence = 'authoritative'
          AND c.current_status IN ('available', 'pending_delete', 'redemption_period', 'expiring_soon')
          AND c.hard_filtered IS NOT TRUE
          AND NOT EXISTS (
            SELECT 1 FROM registrar_quotes rq
            WHERE rq.candidate_id = c.id
              AND rq.observed_at > now() - (:stale || ' days')::interval
          )
        ORDER BY c.composite_score DESC NULLS LAST, c.last_observed DESC
        LIMIT :lim
        """
    )
    res = await session.execute(
        sql, {"stale": str(STALE_AFTER_DAYS), "lim": batch_size}
    )
    return [(row[0], row[1]) for row in res.all()]


async def _persist(session: AsyncSession, candidate_id: int, quote: RegistrarQuoteResult) -> None:
    session.add(
        RegistrarQuote(
            candidate_id=candidate_id,
            registrar=quote.registrar,
            is_premium=quote.is_premium,
            quote_price_micros=quote.quote_price_micros,
            renewal_price_micros=quote.renewal_price_micros,
            quote_currency=quote.currency,
            api_cost_micros=quote.api_cost_micros,
            raw_response=quote.raw_response,
        )
    )
    cand = await session.get(Candidate, candidate_id)
    if cand is not None:
        cand.score_version = None


async def run_batch(*, batch_size: int) -> int:
    if not settings.porkbun_api_key or not settings.porkbun_secret_api_key:
        log.info("worker.registrar.skipped", reason="porkbun credentials not configured")
        return 0

    async with session_scope() as session:
        rows = await _claim_batch(session, batch_size=batch_size)
    if not rows:
        return 0

    processed = 0
    for cid, domain in rows:
        try:
            quote = await quote_domain(domain)
        except Exception as e:
            log.warning("worker.registrar.error", domain=domain, error=str(e))
            continue
        async with session_scope() as session:
            await _persist(session, cid, quote)
        processed += 1
    log.info("worker.registrar.batch.done", processed=processed)
    return processed


async def _run(shutdown: asyncio.Event, interval_seconds: float) -> None:
    while not shutdown.is_set():
        try:
            await run_batch(batch_size=settings.registrar_batch_size)
        except Exception as e:
            log.error("worker.registrar.batch.error", error=str(e))
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event) -> None:
    def _handler() -> None:
        log.info("worker.registrar.signal.received")
        shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            pass


async def _amain() -> None:
    shutdown = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), shutdown)
    interval = float(settings.registrar_interval_minutes) * 60.0
    log.info("worker.registrar.start", batch_size=settings.registrar_batch_size)
    await _run(shutdown, interval)
    log.info("worker.registrar.exit")


def main() -> None:
    configure_logging()
    from dh.observability import setup_sentry, setup_tracing

    setup_sentry(service="worker-registrar")
    setup_tracing(service="registrar")
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
