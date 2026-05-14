"""Wayback CDX API client — in-tree, polite-rate-limited.

Endpoint: https://web.archive.org/cdx/search/cdx
Free; no key; polite at ~5 req/s.

Replaces `tomnomnom/waybackurls` (unlicensed + dead Common Crawl index).
"""
from __future__ import annotations

import httpx
from aiolimiter import AsyncLimiter
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from dh.logging import log

_CDX_URL = "https://web.archive.org/cdx/search/cdx"
_LIMITER = AsyncLimiter(max_rate=4, time_period=1)


class CdxEntry(BaseModel):
    urlkey: str
    timestamp: str    # YYYYMMDDHHMMSS
    original: str
    mimetype: str | None = None
    statuscode: int | None = None
    digest: str | None = None
    length: int | None = None


class CdxSummary(BaseModel):
    domain: str
    first_capture: str | None = None
    last_capture: str | None = None
    capture_count: int = 0
    entries: list[CdxEntry] = []


def _parse_row(headers: list[str], row: list[str]) -> CdxEntry | None:
    rec = dict(zip(headers, row, strict=False))
    if "original" not in rec or "timestamp" not in rec:
        return None
    sc_raw = rec.get("statuscode")
    sc: int | None = None
    if sc_raw and sc_raw.isdigit():
        sc = int(sc_raw)
    length_raw = rec.get("length")
    ln: int | None = None
    if length_raw and length_raw.isdigit():
        ln = int(length_raw)
    return CdxEntry(
        urlkey=rec.get("urlkey", ""),
        timestamp=rec["timestamp"],
        original=rec["original"],
        mimetype=rec.get("mimetype"),
        statuscode=sc,
        digest=rec.get("digest"),
        length=ln,
    )


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
)
async def fetch_cdx(domain: str, *, limit: int = 10_000) -> CdxSummary:
    """Return a CDX summary for `domain`.

    Uses `collapse=urlkey` to limit duplicate paths and `filter=statuscode:200`
    to focus on real content captures (skip the noise of redirects/404s).
    """
    params = {
        "url": f"{domain}/*",
        "output": "json",
        "limit": str(limit),
        "collapse": "urlkey",
        "filter": "statuscode:200",
        "fl": "urlkey,timestamp,original,mimetype,statuscode,digest,length",
    }
    async with _LIMITER:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(_CDX_URL, params=params)
        if resp.status_code != 200:
            log.warning(
                "wayback.cdx.non200",
                domain=domain,
                status=resp.status_code,
            )
            return CdxSummary(domain=domain)
        try:
            rows = resp.json()
        except ValueError:
            return CdxSummary(domain=domain)

    if not rows:
        return CdxSummary(domain=domain)

    headers = rows[0]
    entries: list[CdxEntry] = []
    for row in rows[1:]:
        entry = _parse_row(headers, row)
        if entry:
            entries.append(entry)

    if not entries:
        return CdxSummary(domain=domain)

    entries.sort(key=lambda e: e.timestamp)
    return CdxSummary(
        domain=domain,
        first_capture=entries[0].timestamp,
        last_capture=entries[-1].timestamp,
        capture_count=len(entries),
        entries=entries,
    )
