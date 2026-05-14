"""APScheduler-backed daily-cron worker.

Jobs:
  - 02:00 UTC daily: publish ``dh:trigger-a2`` on Redis (dh-worker-a2 picks up)
  - 03:30 UTC daily (= 09:00 IST): build today's digest and post to Discord
  - every 5 min: heartbeat log

If DH_DISCORD_WEBHOOK_URL is unset, the digest job logs-and-skips (no error).
"""
from __future__ import annotations

import asyncio
import signal

import orjson
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import desc, select

from dh.api.schemas import CandidateDigestItem
from dh.config import settings
from dh.db.engine import session_scope
from dh.db.models import Candidate, RegistrarQuote
from dh.logging import configure_logging, log
from dh.notifications.discord import post_digest

TRIGGER_A2_CHANNEL = "dh:trigger-a2"
DIGEST_STATUSES = ("available", "pending_delete", "redemption_period", "expiring_soon")


async def _publish_a2_trigger() -> None:
    try:
        import redis.asyncio as redis_async

        client = redis_async.from_url(settings.redis_url, socket_connect_timeout=2)
        try:
            await client.publish(
                TRIGGER_A2_CHANNEL,
                orjson.dumps({"kind": "a2_trigger"}).decode(),
            )
            log.info("scheduler.a2_trigger.published")
        finally:
            await client.aclose()
    except Exception as e:
        log.error("scheduler.a2_trigger.error", error=str(e))


async def _gather_digest() -> list[CandidateDigestItem]:
    async with session_scope() as session:
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
        items: list[CandidateDigestItem] = []
        for cand in rows:
            rq = (
                await session.execute(
                    select(RegistrarQuote)
                    .where(RegistrarQuote.candidate_id == cand.id)
                    .order_by(desc(RegistrarQuote.observed_at))
                    .limit(1)
                )
            ).scalar_one_or_none()
            if (
                rq
                and rq.quote_price_micros
                and rq.quote_price_micros >= settings.premium_ceiling_micros
            ):
                continue
            items.append(
                CandidateDigestItem(
                    domain=cand.domain,
                    composite_score=float(cand.composite_score) if cand.composite_score else None,
                    current_status=cand.current_status,
                    quote_price_micros=rq.quote_price_micros if rq else None,
                )
            )
    return items


async def _send_digest() -> None:
    if not settings.discord_webhook_url:
        log.info("scheduler.digest.skipped", reason="no DH_DISCORD_WEBHOOK_URL")
        return
    items = await _gather_digest()
    try:
        sent = await post_digest(items)
        log.info("scheduler.digest.posted", count=len(items), sent=sent)
    except Exception as e:
        log.error("scheduler.digest.error", error=str(e))


async def _heartbeat() -> None:
    log.info("scheduler.heartbeat")


def _build_scheduler() -> AsyncIOScheduler:
    jobstores = {"default": SQLAlchemyJobStore(url=settings.db_url_sync)}
    sched = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")
    sched.add_job(
        _publish_a2_trigger,
        "cron",
        hour=2,
        minute=0,
        id="a2_trigger_daily",
        replace_existing=True,
    )
    sched.add_job(
        _send_digest,
        "cron",
        hour=3,
        minute=30,
        id="discord_digest_daily",
        replace_existing=True,
    )
    sched.add_job(
        _heartbeat,
        "interval",
        minutes=5,
        id="heartbeat",
        replace_existing=True,
    )
    return sched


async def _amain() -> None:
    sched = _build_scheduler()
    shutdown = asyncio.Event()

    def _handler() -> None:
        log.info("scheduler.signal.received")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            pass

    sched.start()
    log.info("scheduler.start")
    try:
        await shutdown.wait()
    finally:
        sched.shutdown(wait=False)
        log.info("scheduler.exit")


def main() -> None:
    configure_logging()
    from dh.observability import setup_sentry

    setup_sentry(service="scheduler")
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
