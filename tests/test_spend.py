"""Tests for SpendCap.

Avoids fakeredis-aio to keep production deps lean. We monkey-patch the
SpendCap._connect method with a tiny in-memory async stub.
"""
from __future__ import annotations

import pytest

from dh.spend import SpendCap


class _InMemoryRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = seconds
        return True

    async def aclose(self) -> None:  # pragma: no cover
        pass


@pytest.mark.asyncio
async def test_incr_below_cap_does_not_exceed() -> None:
    cap = SpendCap()
    fake = _InMemoryRedis()
    cap._client = fake  # type: ignore[assignment]
    count, exceeded = await cap.incr_and_check("llm_calls", daily_cap=5)
    assert count == 1
    assert exceeded is False


@pytest.mark.asyncio
async def test_incr_over_cap_exceeds() -> None:
    cap = SpendCap()
    fake = _InMemoryRedis()
    cap._client = fake  # type: ignore[assignment]
    for _ in range(5):
        await cap.incr_and_check("llm_calls", daily_cap=5)
    count, exceeded = await cap.incr_and_check("llm_calls", daily_cap=5)
    assert count == 6
    assert exceeded is True


@pytest.mark.asyncio
async def test_separate_keys_are_independent() -> None:
    cap = SpendCap()
    fake = _InMemoryRedis()
    cap._client = fake  # type: ignore[assignment]
    await cap.incr_and_check("a", daily_cap=10)
    count, _ = await cap.incr_and_check("b", daily_cap=10)
    assert count == 1


@pytest.mark.asyncio
async def test_redis_unreachable_fails_open() -> None:
    cap = SpendCap(redis_url="redis://invalid:1/0")
    # Don't pre-connect; let connect attempt fail naturally.
    count, exceeded = await cap.incr_and_check("nope", daily_cap=10)
    assert count == 0
    assert exceeded is False
