"""Porkbun registrar quote lookup.

Uses Porkbun API v3 `domain/checkDomain/{domain}`. The endpoint returns
availability and current registration/renewal pricing, and is rate-limited
by account. We use it only after RDAP says a domain is acquirable.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx
from aiolimiter import AsyncLimiter
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from dh.config import settings
from dh.logging import log
from dh.spend import PORKBUN_QUOTE_KEY, get_default_cap

_API_ROOT = "https://api.porkbun.com/api/json/v3"
_LIMITER = AsyncLimiter(max_rate=1, time_period=10)


class RegistrarQuoteResult(BaseModel):
    domain: str
    registrar: str = "porkbun"
    is_available: bool | None = None
    is_premium: bool | None = None
    quote_price_micros: int | None = None
    renewal_price_micros: int | None = None
    currency: str = "USD"
    api_cost_micros: int = 0
    raw_response: dict[str, object] | None = None


def _usd_to_micros(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int((Decimal(str(value)) * Decimal("1000000")).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=2, max=30),
)
async def quote_domain(domain: str) -> RegistrarQuoteResult:
    """Return Porkbun quote data, or an unknown quote if credentials/caps block it."""
    if not settings.porkbun_api_key or not settings.porkbun_secret_api_key:
        return RegistrarQuoteResult(
            domain=domain,
            raw_response={"reason": "DH_PORKBUN_API_KEY/DH_PORKBUN_SECRET_API_KEY not configured"},
        )

    _, exceeded = await get_default_cap().incr_and_check(
        PORKBUN_QUOTE_KEY, settings.porkbun_daily_quote_cap
    )
    if exceeded:
        return RegistrarQuoteResult(
            domain=domain,
            raw_response={"reason": "porkbun daily quote cap exceeded"},
        )

    payload = {
        "apikey": settings.porkbun_api_key,
        "secretapikey": settings.porkbun_secret_api_key,
    }
    async with _LIMITER:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{_API_ROOT}/domain/checkDomain/{domain}", json=payload)
            if resp.status_code == 429:
                log.warning("porkbun.rate_limited", domain=domain)
            resp.raise_for_status()
            data = resp.json()

    avail = str(data.get("avail", "")).lower()
    is_available = True if avail == "yes" else False if avail == "no" else None
    price = _usd_to_micros(data.get("price") or data.get("registration") or data.get("register"))
    renewal = _usd_to_micros(data.get("renewal") or data.get("renewalPrice"))
    premium_raw = data.get("premium")
    is_premium = None
    if isinstance(premium_raw, bool):
        is_premium = premium_raw
    elif isinstance(premium_raw, str):
        is_premium = premium_raw.lower() in {"yes", "true", "1"}
    if is_available is False:
        price = None

    return RegistrarQuoteResult(
        domain=domain,
        is_available=is_available,
        is_premium=is_premium,
        quote_price_micros=price,
        renewal_price_micros=renewal,
        api_cost_micros=0,
        raw_response=data,
    )
