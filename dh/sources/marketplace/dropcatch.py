"""DropCatch's public pending-delete inventory and domain detail endpoints.

The website explicitly offers the upcoming five-day CSV free of charge for
offline/bulk analysis. This client is read-only: it has no authenticated
account, backorder, bid, or purchase method.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import zipfile
from collections.abc import Collection
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import cast
from urllib.parse import quote, urlparse

import httpx
from aiolimiter import AsyncLimiter

_FILE_URL = "https://client.dropcatch.com/GetFileUrl"
_DETAIL_URL = "https://client.dropcatch.com/GetDomainDetail"
_DOWNLOAD_HOST = "dropcatch-downloads.s3.amazonaws.com"
_DETAIL_LIMITER = AsyncLimiter(max_rate=4, time_period=1)
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z0-9-]{2,63}$")


class DropCatchSourceError(RuntimeError):
    """The public feed or detail response did not match its expected contract."""


@dataclass(frozen=True, slots=True)
class DropCatchListing:
    domain: str
    tld: str
    record_type: str
    drop_date: dt.date

    @property
    def external_key(self) -> str:
        return f"{self.domain}:{self.drop_date.isoformat()}:pending-delete"

    @property
    def listing_url(self) -> str:
        return f"https://www.dropcatch.com/domain/{quote(self.domain, safe='.')}"


@dataclass(frozen=True, slots=True)
class DropCatchFeed:
    listings: tuple[DropCatchListing, ...]
    fetched_count: int
    source_version: str


@dataclass(frozen=True, slots=True)
class DropCatchDetail:
    domain: str
    external_id: str | None
    record_type: str | None
    closes_at: dt.datetime | None
    minimum_price_micros: int | None
    current_price_micros: int | None
    bid_count: int | None
    raw_response: dict[str, object]


def _object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, object]", value)


def _parse_iso_datetime(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _usd_to_micros(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int((Decimal(str(value)) * Decimal("1000000")).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _parse_feed_archive(
    content: bytes,
    *,
    allowed_tlds: Collection[str],
    min_sld_length: int,
    max_sld_length: int,
) -> tuple[tuple[DropCatchListing, ...], int, str]:
    allowed = {t.lower().lstrip(".") for t in allowed_tlds}
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise DropCatchSourceError("DropCatch response was not a valid ZIP archive") from exc
    with archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
            raise DropCatchSourceError("DropCatch archive must contain exactly one CSV")
        member = members[0]
        if member.file_size > 512 * 1024 * 1024:
            raise DropCatchSourceError("DropCatch CSV exceeds the 512 MiB safety limit")
        source_version = member.filename
        listings: list[DropCatchListing] = []
        fetched_count = 0
        with archive.open(member) as raw:
            with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text_stream:
                reader = csv.DictReader(text_stream)
                required = {"Domain", "TLD", "Type", "Drop Date"}
                if not reader.fieldnames or not required.issubset(reader.fieldnames):
                    raise DropCatchSourceError("DropCatch CSV columns changed")
                for row in reader:
                    fetched_count += 1
                    domain = (row.get("Domain") or "").strip().lower().rstrip(".")
                    tld = (row.get("TLD") or "").strip().lower().lstrip(".")
                    if tld not in allowed or not _DOMAIN_RE.fullmatch(domain):
                        continue
                    sld, actual_tld = domain.rsplit(".", 1)
                    if actual_tld != tld:
                        continue
                    if not sld.isascii() or not sld.isalpha():
                        continue
                    if not min_sld_length <= len(sld) <= max_sld_length:
                        continue
                    try:
                        drop_date = dt.date.fromisoformat((row.get("Drop Date") or "").strip())
                    except ValueError:
                        continue
                    listings.append(
                        DropCatchListing(
                            domain=domain,
                            tld=tld,
                            record_type=(row.get("Type") or "PendingDelete").strip(),
                            drop_date=drop_date,
                        )
                    )
    return tuple(listings), fetched_count, source_version


async def fetch_pending_delete_feed(
    *,
    allowed_tlds: Collection[str] = ("com",),
    min_sld_length: int = 4,
    max_sld_length: int = 18,
    client: httpx.AsyncClient | None = None,
) -> DropCatchFeed:
    """Fetch and prefilter the free five-day pending-delete CSV."""
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=120, follow_redirects=True)
    try:
        url_response = await http.get(
            _FILE_URL,
            params={
                "FileType": "CSV",
                "RequestType": "Dropping",
                "BackorderDay": "AllDays",
            },
            timeout=30,
        )
        url_response.raise_for_status()
        body = _object_dict(url_response.json())
        if body is None:
            raise DropCatchSourceError("DropCatch download response was not an object")
        result = _object_dict(body.get("result"))
        file_url = result.get("fileUrl") if result else None
        if body.get("success") is not True or not isinstance(file_url, str):
            raise DropCatchSourceError("DropCatch did not return a download URL")
        parsed = urlparse(file_url)
        if parsed.scheme != "https" or parsed.hostname != _DOWNLOAD_HOST:
            raise DropCatchSourceError("DropCatch returned an untrusted download host")
        archive_response = await http.get(file_url, timeout=120)
        archive_response.raise_for_status()
        if len(archive_response.content) > 64 * 1024 * 1024:
            raise DropCatchSourceError("DropCatch archive exceeds the 64 MiB safety limit")
        listings, fetched_count, source_version = _parse_feed_archive(
            archive_response.content,
            allowed_tlds=allowed_tlds,
            min_sld_length=min_sld_length,
            max_sld_length=max_sld_length,
        )
        return DropCatchFeed(
            listings=listings,
            fetched_count=fetched_count,
            source_version=source_version,
        )
    finally:
        if owns_client:
            await http.aclose()


async def fetch_domain_detail(
    domain: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> DropCatchDetail:
    """Read the public price/deadline detail for one known inventory domain."""
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
    try:
        async with _DETAIL_LIMITER:
            response = await http.get(
                _DETAIL_URL,
                params={"DomainName": domain},
                timeout=30,
            )
        response.raise_for_status()
        body = _object_dict(response.json())
        if body is None:
            raise DropCatchSourceError(f"DropCatch detail for {domain} was not an object")
        result = _object_dict(body.get("result"))
        item = _object_dict(result.get("item")) if result else None
        if body.get("success") is not True or not isinstance(item, dict):
            raise DropCatchSourceError(f"DropCatch has no detail for {domain}")
        return DropCatchDetail(
            domain=domain.lower(),
            external_id=(str(item["id"]) if item.get("id") is not None else None),
            record_type=(str(item["recordType"]) if item.get("recordType") else None),
            closes_at=_parse_iso_datetime(item.get("expirationDate")),
            minimum_price_micros=_usd_to_micros(item.get("nextValidBid")),
            current_price_micros=_usd_to_micros(item.get("highBid")),
            bid_count=_as_int(item.get("bidCount")),
            raw_response=item,
        )
    finally:
        if owns_client:
            await http.aclose()
