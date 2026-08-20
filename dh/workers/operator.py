"""Low-concurrency executor for typed XD jobs; never executes shell commands."""

from __future__ import annotations

import asyncio
import signal

from dh.config import settings
from dh.jobs import PartialJobError, claim_next_job, execute_job, finish_job
from dh.logging import configure_logging, log


async def _run(shutdown: asyncio.Event) -> None:
    while not shutdown.is_set():
        job = await claim_next_job(settings.operator_worker_name)
        if job is None:
            try:
                await asyncio.wait_for(
                    shutdown.wait(), timeout=max(1, settings.operator_job_interval_seconds)
                )
            except TimeoutError:
                continue
            continue
        try:
            result = await execute_job(job)
        except PartialJobError as exc:
            await finish_job(job.id, state="partial", error=str(exc))
        except Exception as exc:
            log.exception("worker.operator.job.failed", job_id=job.id, kind=job.kind)
            await finish_job(job.id, state="failed", error=f"{type(exc).__name__}: {exc}")
        else:
            await finish_job(job.id, state="success", result=result)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event) -> None:
    def stop() -> None:
        shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop)
        except (NotImplementedError, RuntimeError):
            pass


async def _amain() -> None:
    shutdown = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), shutdown)
    await _run(shutdown)


def main() -> None:
    configure_logging()
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
