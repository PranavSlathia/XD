"""Continuous A2 (GitHub README/docs dead-link) worker.

Runs ``run_a2_spike`` in an infinite loop with SpikeConfig populated from env.
Sleeps ``DH_A2_INTERVAL_HOURS`` between iterations. Handles SIGTERM/SIGINT
gracefully — sets a cancellation event, lets the current iteration finish,
then exits.
"""
from __future__ import annotations

import asyncio
import signal
from typing import Any

from dh.config import settings
from dh.logging import configure_logging, log


def _build_spike_config() -> Any:
    """Build a SpikeConfig from env. Imported lazily so tests can patch."""
    from dh.spikes.a2 import SpikeConfig

    return SpikeConfig(
        n_repos=settings.a2_n_repos,
        star_floor=settings.a2_star_floor,
        pushed_before=settings.a2_pushed_before or None,
        persist=True,
    )


async def loop_once() -> None:
    """One iteration. Imports lazily so tests can monkeypatch run_a2_spike."""
    from dh.spikes.a2 import run_a2_spike

    cfg = _build_spike_config()
    log.info("worker.a2.iter.start", n_repos=cfg.n_repos, star_floor=cfg.star_floor)
    await run_a2_spike(cfg)
    log.info("worker.a2.iter.done")


async def _run(shutdown: asyncio.Event, interval_seconds: float) -> None:
    while not shutdown.is_set():
        try:
            await loop_once()
        except Exception as e:
            log.error("worker.a2.iter.error", error=str(e))
        # Sleep until interval elapses or shutdown signalled.
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event) -> None:
    def _handler() -> None:
        log.info("worker.a2.signal.received")
        shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            # Windows / non-main thread: rely on KeyboardInterrupt propagation.
            pass


async def _amain() -> None:
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop, shutdown)
    interval_seconds = float(settings.a2_interval_hours) * 3600.0
    log.info(
        "worker.a2.start",
        interval_hours=settings.a2_interval_hours,
    )
    await _run(shutdown, interval_seconds)
    log.info("worker.a2.exit")


def main() -> None:
    configure_logging()
    from dh.observability import setup_sentry, setup_tracing

    setup_sentry(service="worker-a2")
    setup_tracing(service="a2")
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
