"""Read-only Porkbun availability and price quotes for XD's core six TLDs."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import cast

import httpx
from aiolimiter import AsyncLimiter
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from dh.config import settings
from dh.logging import log
from dh.sources.registrar.core import adapter_for_domain
from dh.spend import PORKBUN_QUOTE_KEY, get_default_cap

_API_ROOT = "https://api.porkbun.com/api/json/v3"
_LIMITER = AsyncLimiter(max_rate=1, time_period=10)


class RegistrarQuoteResult(BaseModel):
    domain: str
    tld: str
    registrar: str = "porkbun"
    is_available: bool | None = None
    is_premium: bool | None = None
    availability_status: str = "unknown"
    price_class: str = "unknown"
    quote_price_micros: int | None = None
    renewal_price_micros: int | None = None
    currency: str = "USD"
    api_cost_micros: int = 0
    observed_at: dt.datetime
    expires_at: dt.datetime
    raw_response: dict[str, object] | None = None


def _usd_to_micros(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int((Decimal(str(value)) * Decimal("1000000")).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


def _as_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    mapping = cast(dict[object, object], value)
    return {str(key): item for key, item in mapping.items()}


def _as_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"yes", "true", "1"}:
        return True
    if normalized in {"no", "false", "0"}:
        return False
    return None


def parse_quote_response(
    domain: str,
    data: dict[str, object],
    *,
    observed_at: dt.datetime | None = None,
) -> RegistrarQuoteResult:
    """Normalize Porkbun's response without treating absence as negative evidence."""

    adapter = adapter_for_domain(domain)
    observed = observed_at or dt.datetime.now(dt.UTC)
    expires = observed + dt.timedelta(seconds=adapter.quote_ttl_seconds)
    status = str(data.get("status", "")).strip().upper()
    response = _as_mapping(data.get("response"))
    # Accept the older flat shape for historical fixtures and audit imports.
    if not response and any(key in data for key in ("avail", "price", "premium")):
        response = _as_mapping(data)
    if status and status != "SUCCESS":
        response = {}

    availability_status = adapter.availability_status(response.get("avail"))
    price = _usd_to_micros(response.get("price"))
    premium = _as_optional_bool(response.get("premium"))
    additional = _as_mapping(response.get("additional"))
    renewal = _as_mapping(additional.get("renewal"))
    renewal_price = _usd_to_micros(
        renewal.get("price") or renewal.get("regularPrice") or response.get("renewal")
    )
    price_class = adapter.price_class(
        availability_status=availability_status,
        quote_type=response.get("type"),
        premium=premium,
        registration_price_micros=price,
    )
    if availability_status == "unavailable":
        price = None
        renewal_price = None

    return RegistrarQuoteResult(
        domain=domain.strip().lower().rstrip("."),
        tld=adapter.tld,
        is_available=(
            True
            if availability_status == "available"
            else False
            if availability_status == "unavailable"
            else None
        ),
        is_premium=premium,
        availability_status=availability_status,
        price_class=price_class,
        quote_price_micros=price,
        renewal_price_micros=renewal_price,
        observed_at=observed,
        expires_at=expires,
        raw_response=data,
    )


def _unknown_quote(domain: str, reason: str) -> RegistrarQuoteResult:
    adapter = adapter_for_domain(domain)
    observed = dt.datetime.now(dt.UTC)
    return RegistrarQuoteResult(
        domain=domain,
        tld=adapter.tld,
        observed_at=observed,
        expires_at=observed + dt.timedelta(seconds=adapter.quote_ttl_seconds),
        raw_response={"reason": reason},
    )


async def _request_quote(
    client: httpx.AsyncClient,
    domain: str,
    *,
    headers: dict[str, str],
) -> dict[str, object]:
    # Porkbun's v3 checkDomain contract is a POST. Header authentication lets
    # the required JSON auth object remain empty while keeping credentials out
    # of request bodies and logs.
    response = await client.post(
        f"{_API_ROOT}/domain/checkDomain/{domain}",
        headers=headers,
        json={},
    )
    if response.status_code == 429:
        log.warning("porkbun.rate_limited", domain=domain)
    response.raise_for_status()
    return _as_mapping(cast(object, response.json()))


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=2, max=30),
)
async def quote_domain(domain: str) -> RegistrarQuoteResult:
    """Return Porkbun quote data, or an unknown quote if credentials/caps block it."""
    adapter_for_domain(domain)
    if not settings.porkbun_api_key or not settings.porkbun_secret_api_key:
        return _unknown_quote(
            domain,
            "DH_PORKBUN_API_KEY/DH_PORKBUN_SECRET_API_KEY not configured",
        )

    _, exceeded = await get_default_cap().incr_and_check(
        PORKBUN_QUOTE_KEY, settings.porkbun_daily_quote_cap
    )
    if exceeded:
        return _unknown_quote(domain, "porkbun daily quote cap exceeded")

    headers = {
        "X-API-Key": settings.porkbun_api_key,
        "X-Secret-API-Key": settings.porkbun_secret_api_key,
    }
    async with _LIMITER:
        async with httpx.AsyncClient(timeout=30) as client:
            data = await _request_quote(client, domain, headers=headers)
    return parse_quote_response(domain, data)
