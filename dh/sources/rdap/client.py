"""RDAP-first availability waterfall (PRD §4.2).

Order (PRD §4.2):
    1. dnspython NXDOMAIN check     — LIVENESS HINT ONLY (never sets `available`)
    2. RDAP via IANA bootstrap      — AUTHORITATIVE
    3. WhoisJSON                    — AUTHORITATIVE fallback for non-RDAP TLDs
    4. WhoisFreaks                  — AUTHORITATIVE bulk fallback
    5. python-whois                 — LEGACY fallback for ccTLDs

DNS NXDOMAIN is NOT availability.  Code MUST refuse to mark a candidate
`available` based solely on a DNS lookup.

Implementation deferred to Phase 0.5 stub fill-in.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

AvailabilityStatus = Literal[
    "unknown",
    "registered",
    "available",
    "pending_delete",
    "redemption_period",
    "expiring_soon",
    "client_hold",
    "server_hold",
]

AvailabilityConfidence = Literal["authoritative", "probable", "unknown", "conflicting"]


class AvailabilityResult(BaseModel):
    domain: str
    status: AvailabilityStatus
    confidence: AvailabilityConfidence
    source: str                 # 'rdap' | 'whoisjson' | 'whoisfreaks' | 'python-whois' | 'dns'
    epp_statuses: list[str] = []
    expiry_date: str | None = None
    registrar: str | None = None
    cost_micros: int = 0
    raw_response: dict[str, object] | None = None


async def check_availability(domain: str) -> AvailabilityResult:
    """Run the full waterfall and return the most authoritative result."""
    # TODO: implement after Phase 0.5 scaffold is committed.
    raise NotImplementedError(
        "RDAP availability waterfall is a stub. Implementation pending Phase 0.5."
    )
