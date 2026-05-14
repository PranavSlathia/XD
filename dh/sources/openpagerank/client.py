"""DomCop Open PageRank client.

API: GET https://openpagerank.com/api/v1.0/getPageRank?domains[]=...
     header: API-OPR: <key>
Batch up to 100 domains per call. Free, unlimited with key (rate limit ~600/min).
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

_OPR_URL = "https://openpagerank.com/api/v1.0/getPageRank"
_LIMITER = AsyncLimiter(max_rate=300, time_period=60)  # well under 600/min


class OPRResult(BaseModel):
    domain: str
    rank: int | None = None
    page_rank_integer: int | None = None
    page_rank_decimal: float | None = None
    status_code: int | None = None
    error: str | None = None
    found: bool = False


class OPRBatchResult(BaseModel):
    results: list[OPRResult]
    api_cost_micros: int = 0


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
)
async def _opr_chunk(
    client: httpx.AsyncClient, chunk: Sequence[str]
) -> list[OPRResult]:
    async with _LIMITER:
        params = [("domains[]", d) for d in chunk]
        resp = await client.get(
            _OPR_URL,
            params=params,
            headers={"API-OPR": settings.openpagerank_api_key},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
    out: list[OPRResult] = []
    for r in body.get("response", []):
        domain = r.get("domain", "")
        out.append(
            OPRResult(
                domain=domain,
                rank=r.get("rank") if isinstance(r.get("rank"), int) else None,
                page_rank_integer=r.get("page_rank_integer"),
                page_rank_decimal=(
                    float(r["page_rank_decimal"])
                    if r.get("page_rank_decimal") not in (None, "")
                    else None
                ),
                status_code=r.get("status_code"),
                error=r.get("error") or None,
                found=r.get("status_code") == 200,
            )
        )
    return out


async def fetch_open_pagerank(domains: Sequence[str]) -> OPRBatchResult:
    """Look up Open PageRank for any number of domains. Batches in 100s."""
    if not settings.openpagerank_api_key:
        log.warning(
            "openpagerank.no_key",
            note="DH_OPENPAGERANK_API_KEY empty; returning empty results",
        )
        return OPRBatchResult(
            results=[OPRResult(domain=d, error="no_api_key") for d in domains]
        )

    results: list[OPRResult] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for i in range(0, len(domains), 100):
            chunk = domains[i : i + 100]
            try:
                results.extend(await _opr_chunk(client, chunk))
            except httpx.HTTPError as e:
                log.warning("openpagerank.error", n=len(chunk), error=str(e))
                results.extend(
                    OPRResult(domain=d, error=str(e)) for d in chunk
                )
    return OPRBatchResult(results=results)
