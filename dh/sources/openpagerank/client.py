# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
"""OpenPageRank API client with the 2026 endpoint and legacy-key fallback.

New keys (``opr_*``) use Keywords Everywhere's bearer-authenticated bulk API.
The legacy DomCop endpoint remains supported only so an existing installation
does not fail abruptly before that service is retired on 2026-09-30. Primary
inventory discovery uses the published Top-10-Million dataset and needs no key.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
from aiolimiter import AsyncLimiter
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from dh.config import settings
from dh.logging import log

_NEW_OPR_URL = "https://openpagerank.keywordseverywhere.com/v1/domains/bulk"
_LEGACY_OPR_URL = "https://openpagerank.com/api/v1.0/getPageRank"
_LIMITER = AsyncLimiter(max_rate=50, time_period=60)


class OPRResult(BaseModel):
    domain: str
    rank: int | None = None
    page_rank_integer: int | None = None
    page_rank_decimal: float | None = None
    referring_domains: int | None = None
    status_code: int | None = None
    error: str | None = None
    found: bool = False


class OPRBatchResult(BaseModel):
    results: list[OPRResult]
    api_cost_micros: int = 0


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
async def _opr_chunk_new(client: httpx.AsyncClient, chunk: Sequence[str]) -> list[OPRResult]:
    async with _LIMITER:
        response = await client.post(
            _NEW_OPR_URL,
            headers={"Authorization": f"Bearer {settings.openpagerank_api_key}"},
            json={"domains": list(chunk), "include_history": False},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    output: list[OPRResult] = []
    for row in body.get("results", []):
        score = _as_float(row.get("open_page_rank"))
        found = row.get("found") is True and score is not None
        output.append(
            OPRResult(
                domain=str(row.get("domain") or ""),
                rank=_as_int(row.get("rank")),
                page_rank_integer=(int(score) if score is not None else None),
                page_rank_decimal=score,
                referring_domains=_as_int(row.get("referring_domains")),
                status_code=200,
                found=found,
            )
        )
    return output


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
async def _opr_chunk_legacy(client: httpx.AsyncClient, chunk: Sequence[str]) -> list[OPRResult]:
    async with _LIMITER:
        response = await client.get(
            _LEGACY_OPR_URL,
            params={"domains[]": list(chunk)},
            headers={"API-OPR": settings.openpagerank_api_key},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    output: list[OPRResult] = []
    for row in body.get("response", []):
        score = _as_float(row.get("page_rank_decimal"))
        status_code = _as_int(row.get("status_code"))
        output.append(
            OPRResult(
                domain=str(row.get("domain") or ""),
                rank=_as_int(row.get("rank")),
                page_rank_integer=_as_int(row.get("page_rank_integer")),
                page_rank_decimal=score,
                status_code=status_code,
                error=(str(row["error"]) if row.get("error") else None),
                found=status_code == 200 and score is not None,
            )
        )
    return output


async def fetch_open_pagerank(domains: Sequence[str]) -> OPRBatchResult:
    """Look up OpenPageRank for any number of domains, in batches of 100."""
    if not settings.openpagerank_api_key:
        log.warning(
            "openpagerank.no_key",
            note="API enrichment disabled; inventory still uses the public reference dataset",
        )
        return OPRBatchResult(
            results=[OPRResult(domain=domain, error="no_api_key") for domain in domains]
        )

    is_new_key = settings.openpagerank_api_key.startswith("opr_")
    if not is_new_key:
        log.warning(
            "openpagerank.legacy_key",
            retirement_date="2026-09-30",
            action="replace DH_OPENPAGERANK_API_KEY with an opr_* key",
        )

    results: list[OPRResult] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for index in range(0, len(domains), 100):
            chunk = domains[index : index + 100]
            try:
                if is_new_key:
                    results.extend(await _opr_chunk_new(client, chunk))
                else:
                    results.extend(await _opr_chunk_legacy(client, chunk))
            except httpx.HTTPError as exc:
                log.warning("openpagerank.error", n=len(chunk), error=str(exc))
                results.extend(OPRResult(domain=domain, error=str(exc)) for domain in chunk)
    return OPRBatchResult(results=results)
