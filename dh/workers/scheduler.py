# pyright: reportUnknownMemberType=false
"""APScheduler-backed autonomous discovery scheduler.

Jobs:
  - 02:00 UTC daily: publish ``dh:trigger-a2`` on Redis for ``dh-worker-a2``
  - every 5 min: heartbeat log
"""
from __future__ import annotations

import asyncio
import signal

import orjson
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from dh.config import settings
from dh.logging import configure_logging, log

TRIGGER_A2_CHANNEL = "dh:trigger-a2"


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
    from dh.observability import setup_sentry, setup_tracing

    setup_sentry(service="scheduler")
    setup_tracing(service="scheduler")
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
