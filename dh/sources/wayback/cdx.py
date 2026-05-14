"""Wayback CDX API client — `dh.wayback.cdx`.

Replaces `tomnomnom/waybackurls` (unlicensed + 8-year-dead CC index, per
docs/IMPLEMENTATION_NOTES.md). About 30 LoC when filled in.

Free API. Polite rate-limit (~5 req/s) via aiolimiter.

Endpoint: https://web.archive.org/cdx/search/cdx
"""
from __future__ import annotations

from pydantic import BaseModel


class CdxEntry(BaseModel):
    urlkey: str
    timestamp: str   # YYYYMMDDHHMMSS
    original: str
    mimetype: str | None = None
    statuscode: int | None = None
    digest: str | None = None
    length: int | None = None


class CdxSummary(BaseModel):
    """Aggregate computed from a domain's full CDX history."""
    domain: str
    first_capture: str | None = None
    last_capture: str | None = None
    capture_count: int = 0
    entries: list[CdxEntry] = []


async def fetch_cdx(domain: str, *, limit: int = 10_000) -> CdxSummary:
    """Fetch CDX history for a domain. Polite, retried, rate-limited."""
    # TODO: implement after spike scaffold committed.
    raise NotImplementedError("Wayback CDX client is a stub.")
