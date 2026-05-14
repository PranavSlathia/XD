"""Smoke test the A2 worker loop: SIGTERM-equivalent shuts it down cleanly."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_loop_calls_run_and_shuts_down() -> None:
    from dh.workers import a2 as worker

    calls = 0

    async def fake_run(_cfg: object) -> None:
        nonlocal calls
        calls += 1

    shutdown = asyncio.Event()

    with patch("dh.spikes.a2.run_a2_spike", AsyncMock(side_effect=fake_run)):
        task = asyncio.create_task(worker._run(shutdown, interval_seconds=0.01))
        # Let one iteration run.
        await asyncio.sleep(0.05)
        shutdown.set()
        await asyncio.wait_for(task, timeout=1.0)

    assert calls >= 1


@pytest.mark.asyncio
async def test_loop_continues_on_error() -> None:
    from dh.workers import a2 as worker

    attempts = 0

    async def flaky(_cfg: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("boom")

    shutdown = asyncio.Event()

    with patch("dh.spikes.a2.run_a2_spike", AsyncMock(side_effect=flaky)):
        task = asyncio.create_task(worker._run(shutdown, interval_seconds=0.01))
        await asyncio.sleep(0.1)
        shutdown.set()
        await asyncio.wait_for(task, timeout=1.0)

    assert attempts >= 2
