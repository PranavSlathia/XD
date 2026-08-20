from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, cast

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from dh.config import settings
from dh.engine.configuration import get_active_config
from dh.providers.base import BacklinkRecord, BacklinkSummary
from dh.providers.budget import reserve_provider_budget, settle_provider_budget

BASE_URL = "https://api.dataforseo.com"


class DataForSEOError(RuntimeError):
    pass


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, dict) else {}


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _optional_integer(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


class DataForSEOBacklinkProvider:
    name = "dataforseo"

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        if not settings.dataforseo_login or not settings.dataforseo_password:
            raise DataForSEOError("DataForSEO credentials are not configured")
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=BASE_URL,
            auth=(settings.dataforseo_login, settings.dataforseo_password),
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": "XD-Domain-Hunter/1.0"},
        )

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def _post(
        self,
        session: AsyncSession,
        *,
        path: str,
        operation: str,
        payload: dict[str, Any],
        candidate_id: int | None = None,
    ) -> tuple[Mapping[str, object], int]:
        _row, config = await get_active_config(session)
        request_id = str(uuid.uuid4())
        reservation = await reserve_provider_budget(
            session,
            provider=self.name,
            operation=operation,
            request_id=request_id,
            reserve_micros=config.paid_enrichment.operation_reserve_micros,
            monthly_cap_micros=config.paid_enrichment.monthly_budget_micros,
            candidate_id=candidate_id,
        )
        response = await self._client.post(path, json=[payload])
        response.raise_for_status()
        body = _mapping(cast(object, response.json()))
        if _integer(body.get("status_code")) != 20000:
            raise DataForSEOError(str(body.get("status_message") or "provider request failed"))
        tasks = body.get("tasks")
        task_values = cast(list[object], tasks) if isinstance(tasks, list) else []
        task: Mapping[str, object] = _mapping(task_values[0]) if task_values else {}
        cost_value: object | None = task.get("cost")
        cost_micros = round(float(cost_value) * 1_000_000) if isinstance(cost_value, int | float) else 0
        await settle_provider_budget(
            session,
            reservation_id=reservation.id,
            operation=operation,
            actual_cost_micros=cost_micros,
        )
        task_status_value: object | None = task.get("status_code")
        task_status = _integer(task_status_value)
        if task_status != 20000:
            task_message = task.get("status_message")
            raise DataForSEOError(
                task_message if isinstance(task_message, str) else "provider task failed"
            )
        result: object | None = task.get("result")
        result_values = cast(list[object], result) if isinstance(result, list) else []
        first: Mapping[str, object] = _mapping(result_values[0]) if result_values else {}
        return first, cost_micros

    async def summary(self, session: AsyncSession, target: str) -> BacklinkSummary:
        result, cost_micros = await self._post(
            session,
            path="/v3/backlinks/summary/live",
            operation="backlinks_summary",
            payload={
                "target": target,
                "include_subdomains": True,
                "backlinks_status_type": "live",
                "backlinks_filters": [["dofollow", "=", True]],
            },
        )
        return BacklinkSummary(
            target=target,
            backlinks=_integer(result.get("backlinks")),
            referring_domains=_integer(result.get("referring_domains")),
            referring_main_domains=_integer(result.get("referring_main_domains")),
            referring_ips=_integer(result.get("referring_ips")),
            rank=_optional_integer(result.get("rank")),
            provider=self.name,
            cost_micros=cost_micros,
        )

    async def backlinks(
        self, session: AsyncSession, target: str, *, limit: int = 100
    ) -> tuple[BacklinkRecord, ...]:
        result, _cost_micros = await self._post(
            session,
            path="/v3/backlinks/backlinks/live",
            operation="backlinks_pages",
            payload={
                "target": target,
                "mode": "one_per_domain",
                "limit": max(1, min(limit, 1000)),
                "filters": [["dofollow", "=", True], "and", ["is_lost", "=", False]],
                "order_by": ["rank,desc"],
            },
        )
        raw_items_value = result.get("items")
        if not isinstance(raw_items_value, list):
            return ()
        raw_items = cast(list[object], raw_items_value)
        items: list[BacklinkRecord] = []
        for raw in raw_items:
            item = _mapping(raw)
            source_url = _optional_string(item.get("url_from"))
            source_domain = _optional_string(item.get("domain_from"))
            target_url = _optional_string(item.get("url_to"))
            if not source_url or not source_domain or not target_url:
                continue
            items.append(
                BacklinkRecord(
                    source_url=source_url,
                    source_domain=source_domain,
                    target_url=target_url,
                    anchor=_optional_string(item.get("anchor")),
                    text_before=_optional_string(item.get("text_pre")),
                    text_after=_optional_string(item.get("text_post")),
                    semantic_location=_optional_string(item.get("semantic_location")),
                    dofollow=bool(item.get("dofollow")),
                    source_rank=_optional_integer(item.get("page_from_rank")),
                    first_seen=_optional_string(item.get("first_seen")),
                    lost_date=_optional_string(item.get("lost_date")),
                )
            )
        return tuple(items)
