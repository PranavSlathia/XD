"""RDAP-first availability waterfall (PRD §4.2).

Order:
    1. dnspython NXDOMAIN check    — LIVENESS HINT ONLY (never sets `available`)
    2. RDAP via IANA bootstrap     — AUTHORITATIVE
    3. WhoisJSON                   — AUTHORITATIVE fallback for non-RDAP TLDs
    (4. WhoisFreaks                — stub for now; engage if WhoisJSON quota hit)
    (5. python-whois               — stub for now; ccTLD legacy fallback)

DNS NXDOMAIN is NOT authoritative availability. Always confirm via RDAP/WhoisJSON
before marking a candidate `available`.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Literal

import dns.asyncresolver
import dns.resolver
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
    source: str
    epp_statuses: list[str] = []
    expiry_date: str | None = None
    registrar: str | None = None
    api_cost_micros: int = 0
    raw_response: dict[str, object] | None = None


# Polite rate limits. RDAP servers don't publish a universal RPS; ~5/s is safe.
_RDAP_LIMITER = AsyncLimiter(max_rate=5, time_period=1)
_WHOISJSON_LIMITER = AsyncLimiter(max_rate=2, time_period=1)
_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
_WHOISJSON_URL = "https://whoisjson.com/api/v1/whois"


# --------------------------------------------------------------------------- #
# 1. DNS hint
# --------------------------------------------------------------------------- #

async def dns_is_nxdomain(domain: str) -> bool:
    """Returns True if the domain has NO authoritative NS records.

    Tells you the domain is *worth* a paid availability check.
    Does NOT prove it's available.
    """
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = 5.0
    try:
        await resolver.resolve(domain, "NS")
        return False
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return True
    except dns.resolver.NoNameservers:
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("dns.error", domain=domain, error=str(e))
        return False


# Back-compat alias (older code referenced the private name).
_dns_is_nxdomain = dns_is_nxdomain


# --------------------------------------------------------------------------- #
# 2. RDAP bootstrap + query
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=1)
def _bootstrap_cache() -> dict[str, list[str]]:
    """Cache slot — populated by `_load_bootstrap`."""
    return {}


_bootstrap_lock = asyncio.Lock()


async def _load_bootstrap(client: httpx.AsyncClient) -> dict[str, list[str]]:
    """Load and cache IANA's RDAP bootstrap registry: TLD → [server-URLs]."""
    cache = _bootstrap_cache()
    if cache:
        return cache
    async with _bootstrap_lock:
        if cache:
            return cache
        resp = await client.get(_BOOTSTRAP_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for entry in data.get("services", []):
            tlds, servers = entry[0], entry[1]
            for tld in tlds:
                cache[tld.lower()] = [s.rstrip("/") for s in servers]
    return cache


def _tld_of(domain: str) -> str:
    return domain.rsplit(".", 1)[-1].lower()


def _epp_to_status(epp_statuses: list[str]) -> AvailabilityStatus:
    """Map RDAP/EPP status codes to our compact status enum."""
    s = {x.lower() for x in epp_statuses}
    if "pending delete" in s or "pendingdelete" in s:
        return "pending_delete"
    if "redemption period" in s or "redemptionperiod" in s:
        return "redemption_period"
    if "client hold" in s or "clienthold" in s:
        return "client_hold"
    if "server hold" in s or "serverhold" in s:
        return "server_hold"
    # Anything resolvable + no special flag → registered.
    return "registered"


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=1, max=10),
)
async def _rdap_query(client: httpx.AsyncClient, domain: str) -> AvailabilityResult:
    bootstrap = await _load_bootstrap(client)
    tld = _tld_of(domain)
    servers = bootstrap.get(tld)
    if not servers:
        return AvailabilityResult(
            domain=domain,
            status="unknown",
            confidence="unknown",
            source="rdap",
            raw_response={"reason": f"no RDAP server in bootstrap for .{tld}"},
        )
    last_err: str | None = None
    for base in servers:
        url = f"{base}/domain/{domain}"
        async with _RDAP_LIMITER:
            try:
                resp = await client.get(
                    url,
                    headers={"Accept": "application/rdap+json"},
                    timeout=15,
                )
            except httpx.HTTPError as e:
                last_err = f"{base}: {e}"
                continue
        if resp.status_code == 404:
            return AvailabilityResult(
                domain=domain,
                status="available",
                confidence="authoritative",
                source="rdap",
                raw_response={"rdap_server": base, "http_status": 404},
            )
        if resp.status_code >= 500:
            last_err = f"{base}: HTTP {resp.status_code}"
            continue
        if resp.status_code != 200:
            last_err = f"{base}: HTTP {resp.status_code}"
            continue
        data = resp.json()
        epp = [str(s) for s in data.get("status", [])]
        expiry = None
        registrar = None
        for event in data.get("events", []) or []:
            if event.get("eventAction") == "expiration":
                expiry = event.get("eventDate")
                break
        for entity in data.get("entities", []) or []:
            roles = entity.get("roles") or []
            if "registrar" in roles:
                vcard = entity.get("vcardArray") or []
                if len(vcard) >= 2:
                    for item in vcard[1]:
                        if item and item[0] == "fn" and len(item) >= 4:
                            registrar = item[3]
                            break
                break
        return AvailabilityResult(
            domain=domain,
            status=_epp_to_status(epp),
            confidence="authoritative",
            source="rdap",
            epp_statuses=epp,
            expiry_date=expiry,
            registrar=registrar,
            raw_response={"rdap_server": base, "http_status": 200},
        )

    return AvailabilityResult(
        domain=domain,
        status="unknown",
        confidence="unknown",
        source="rdap",
        raw_response={"errors": last_err},
    )


# --------------------------------------------------------------------------- #
# 3. WhoisJSON fallback
# --------------------------------------------------------------------------- #

@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=1, max=10),
)
async def _whoisjson_query(client: httpx.AsyncClient, domain: str) -> AvailabilityResult:
    if not settings.whoisjson_api_key:
        return AvailabilityResult(
            domain=domain,
            status="unknown",
            confidence="unknown",
            source="whoisjson",
            raw_response={"reason": "no DH_WHOISJSON_API_KEY configured"},
        )
    async with _WHOISJSON_LIMITER:
        resp = await client.get(
            _WHOISJSON_URL,
            params={"domain": domain},
            headers={"Authorization": f"Token={settings.whoisjson_api_key}"},
            timeout=30,
        )
    if resp.status_code == 404:
        return AvailabilityResult(
            domain=domain,
            status="available",
            confidence="authoritative",
            source="whoisjson",
            api_cost_micros=100,
            raw_response={"http_status": 404},
        )
    if resp.status_code != 200:
        return AvailabilityResult(
            domain=domain,
            status="unknown",
            confidence="unknown",
            source="whoisjson",
            api_cost_micros=100,
            raw_response={"http_status": resp.status_code},
        )
    data = resp.json()
    # WhoisJSON returns a "status" field: e.g. "registered" / "available"
    raw_status = (data.get("status") or "").lower()
    if raw_status == "available":
        status: AvailabilityStatus = "available"
    elif raw_status == "registered":
        status = "registered"
    else:
        status = "unknown"
    return AvailabilityResult(
        domain=domain,
        status=status,
        confidence="authoritative" if status != "unknown" else "probable",
        source="whoisjson",
        registrar=data.get("registrar"),
        expiry_date=data.get("expires") or data.get("expiry_date"),
        api_cost_micros=100,
        raw_response=data,
    )


# --------------------------------------------------------------------------- #
# Waterfall orchestration
# --------------------------------------------------------------------------- #

async def check_availability(domain: str) -> AvailabilityResult:
    """Run the waterfall and return the most authoritative result.

    DNS gates whether we spend on RDAP. RDAP is authoritative. WhoisJSON
    is the fallback for non-RDAP TLDs.
    """
    domain = domain.lower().strip(".")
    async with httpx.AsyncClient(timeout=30) as client:
        # Always start with RDAP — DNS hint only used for prioritisation.
        try:
            rdap = await _rdap_query(client, domain)
        except httpx.HTTPError as e:
            log.warning("rdap.error", domain=domain, error=str(e))
            rdap = AvailabilityResult(
                domain=domain,
                status="unknown",
                confidence="unknown",
                source="rdap",
                raw_response={"error": str(e)},
            )
        if rdap.confidence == "authoritative":
            return rdap

        # Fall back to WhoisJSON for non-RDAP TLDs (or transient RDAP failures).
        try:
            wj = await _whoisjson_query(client, domain)
        except httpx.HTTPError as e:
            log.warning("whoisjson.error", domain=domain, error=str(e))
            return rdap
        if wj.confidence == "authoritative":
            return wj
        return rdap if rdap.status != "unknown" else wj
