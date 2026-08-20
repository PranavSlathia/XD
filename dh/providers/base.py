from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class BacklinkSummary:
    target: str
    backlinks: int
    referring_domains: int
    referring_main_domains: int
    referring_ips: int
    rank: int | None
    provider: str
    cost_micros: int


@dataclass(frozen=True, slots=True)
class BacklinkRecord:
    source_url: str
    source_domain: str
    target_url: str
    anchor: str | None
    text_before: str | None
    text_after: str | None
    semantic_location: str | None
    dofollow: bool
    source_rank: int | None
    first_seen: str | None
    lost_date: str | None


class BacklinkProvider(Protocol):
    async def summary(self, session: AsyncSession, target: str) -> BacklinkSummary: ...

    async def backlinks(
        self, session: AsyncSession, target: str, *, limit: int = 100
    ) -> tuple[BacklinkRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class SearchDemandEvidence:
    target: str
    monthly_searches: int | None
    cost_per_click_micros: int | None
    advertiser_competition: float | None
    provider: str
    cost_micros: int


class SearchDemandProvider(Protocol):
    async def evidence(
        self, session: AsyncSession, target: str
    ) -> SearchDemandEvidence: ...


@dataclass(frozen=True, slots=True)
class ComparableSale:
    domain: str
    sale_price_micros: int
    currency: str
    sold_at: dt.date | None
    venue: str | None
    source_reference: str


@dataclass(frozen=True, slots=True)
class ComparableSalesEvidence:
    target: str
    sales: tuple[ComparableSale, ...]
    licensed_source: bool
    provider: str
    cost_micros: int


class ComparableSalesProvider(Protocol):
    async def evidence(
        self, session: AsyncSession, target: str, *, limit: int = 20
    ) -> ComparableSalesEvidence: ...


@dataclass(frozen=True, slots=True)
class RegistrarAvailabilityQuote:
    domain: str
    tld: str
    registrar: str
    availability_status: str
    price_class: str
    registration_price_micros: int | None
    renewal_price_micros: int | None
    currency: str
    observed_at: dt.datetime
    expires_at: dt.datetime
    raw_response: dict[str, object] | None = None


class RegistrarAvailabilityProvider(Protocol):
    async def quote(self, domain: str) -> RegistrarAvailabilityQuote: ...
