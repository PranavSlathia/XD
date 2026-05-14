"""Hard spend controls backed by Redis counters.

``SpendCap.incr_and_check(key, daily_cap)`` atomically increments today's
counter for ``key`` and returns (current_value, exceeded). The Redis key is
namespaced by UTC date so it auto-resets at midnight.

If Redis is unreachable we fail open (i.e. return ``(0, False)`` and log) —
the alternative (failing closed) would brick the pipeline whenever Redis
hiccups. The structured warning is enough to surface the regression.
"""
from __future__ import annotations

import datetime as dt
from typing import Protocol

import redis.asyncio as redis_async

from dh.config import settings
from dh.logging import log


class _Incrable(Protocol):
    async def incr(self, key: str) -> int: ...
    async def expire(self, key: str, seconds: int) -> bool: ...


def _today_key(name: str, *, today: dt.date | None = None) -> str:
    today = today or dt.datetime.now(dt.UTC).date()
    return f"dh:spend:{name}:{today.isoformat()}"


class SpendCap:
    """Atomic daily-counter cap. Use one instance per process."""

    def __init__(self, *, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or settings.redis_url
        self._client: _Incrable | None = None

    async def _connect(self) -> _Incrable:
        if self._client is None:
            self._client = redis_async.from_url(self._redis_url, socket_connect_timeout=2)  # type: ignore[assignment]
        assert self._client is not None
        return self._client

    async def incr_and_check(
        self, key: str, daily_cap: int, *, today: dt.date | None = None
    ) -> tuple[int, bool]:
        """Atomically bump today's counter for ``key``.

        Returns ``(count_after_incr, exceeded)``. ``exceeded`` is True iff
        ``count_after_incr > daily_cap`` — i.e. this call put us over the cap.
        """
        rkey = _today_key(key, today=today)
        try:
            client = await self._connect()
            count = await client.incr(rkey)
            # 25 hours so the counter survives a brief outage near rollover.
            await client.expire(rkey, 60 * 60 * 25)
        except Exception as e:
            log.warning("spend.redis_error", key=key, error=str(e))
            return 0, False
        exceeded = count > daily_cap
        if exceeded:
            log.warning(
                "spend.cap.exceeded",
                key=key,
                count=count,
                daily_cap=daily_cap,
            )
        return count, exceeded

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()  # type: ignore[attr-defined]
            except Exception as e:
                log.debug("spend.close_error", error=str(e))
            self._client = None


# Pre-defined cap names; centralise so callers don't typo-divergence.
LLM_CALLS_KEY = "llm_calls"
WHOISJSON_KEY = "whoisjson_calls"
WHOISFREAKS_KEY = "whoisfreaks_calls"
BIGQUERY_BYTES_KEY = "bigquery_bytes"


# Convenience module-level singleton for callers that don't manage lifetime.
_default_cap: SpendCap | None = None


def get_default_cap() -> SpendCap:
    global _default_cap
    if _default_cap is None:
        _default_cap = SpendCap()
    return _default_cap
