"""NameBio's free, attribution-required retail keyword statistics dataset."""

from __future__ import annotations

import csv
import datetime as dt
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx
import wordninja

from dh.logging import log

_DATASET_URL = "https://api.namebio.com/retailstats-download"
_MAX_DATASET_BYTES = 64 * 1024 * 1024
_KEYWORD_RE = re.compile(r"^[a-z]{3,24}$")
_PLACEMENTS = ("exact", "start", "end", "middle")
_MARKET_STOPWORDS = frozenset(
    {"all", "and", "best", "for", "from", "get", "new", "online", "the", "top", "with", "your"}
)
_REQUIRED_HEADER = (
    "keyword,exact_sale_count,exact_price_sum,exact_price_avg,exact_price_max,"
    "exact_price_stddev,start_sale_count,start_price_sum,start_price_avg,start_price_max,"
    "start_price_stddev,end_sale_count,end_price_sum,end_price_avg,end_price_max,"
    "end_price_stddev,middle_sale_count,middle_price_sum,middle_price_avg,"
    "middle_price_max,middle_price_stddev"
)


class RetailStatsSourceError(RuntimeError):
    """The NameBio download did not match the documented CSV contract."""


@dataclass(frozen=True, slots=True)
class RetailStatsDataset:
    path: Path
    source_version: str
    refreshed: bool


@dataclass(frozen=True, slots=True)
class PlacementStats:
    sale_count: int
    price_sum: int
    price_avg: float
    price_max: int


@dataclass(frozen=True, slots=True)
class RetailKeywordStats:
    keyword: str
    placements: dict[str, PlacementStats]


@dataclass(frozen=True, slots=True)
class MarketEvidence:
    terms: tuple[str, ...]
    sale_count_floor: int
    price_avg_floor: float
    price_max: int
    placements: tuple[dict[str, object], ...]


def _validate_dataset(path: Path) -> None:
    if path.stat().st_size > _MAX_DATASET_BYTES:
        raise RetailStatsSourceError("NameBio RetailStats CSV exceeds 64 MiB")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        header = stream.readline().strip()
    if header != _REQUIRED_HEADER:
        raise RetailStatsSourceError("NameBio RetailStats CSV columns changed")


def _content_version(response: httpx.Response) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r"retailstats_([0-9]{8})\.csv", disposition)
    if match:
        raw = match.group(1)
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return response.headers.get("last-modified") or dt.date.today().isoformat()


async def ensure_retail_stats_dataset(
    data_dir: Path,
    *,
    refresh_after_hours: int = 24,
    client: httpx.AsyncClient | None = None,
) -> RetailStatsDataset:
    """Return a cached CSV, downloading no more often than configured."""
    target_dir = data_dir / "reference"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "namebio-retailstats.csv"
    max_age = dt.timedelta(hours=max(1, refresh_after_hours))
    if target.exists():
        modified = dt.datetime.fromtimestamp(target.stat().st_mtime, tz=dt.UTC)
        if dt.datetime.now(dt.UTC) - modified < max_age:
            _validate_dataset(target)
            return RetailStatsDataset(
                path=target,
                source_version=modified.date().isoformat(),
                refreshed=False,
            )

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=120, follow_redirects=True)
    temporary = target.with_suffix(".download")
    try:
        async with http.stream("GET", _DATASET_URL, timeout=120) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and int(declared) > _MAX_DATASET_BYTES:
                raise RetailStatsSourceError("NameBio RetailStats CSV exceeds 64 MiB")
            total = 0
            with temporary.open("wb") as output:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                    total += len(chunk)
                    if total > _MAX_DATASET_BYTES:
                        raise RetailStatsSourceError("NameBio RetailStats CSV exceeds 64 MiB")
                    output.write(chunk)
            source_version = _content_version(response)
        _validate_dataset(temporary)
        os.replace(temporary, target)
        return RetailStatsDataset(path=target, source_version=source_version, refreshed=True)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        if target.exists():
            log.warning("namebio.retailstats.refresh_failed_using_stale")
            _validate_dataset(target)
            modified = dt.datetime.fromtimestamp(target.stat().st_mtime, tz=dt.UTC)
            return RetailStatsDataset(
                path=target,
                source_version=f"stale:{modified.date().isoformat()}",
                refreshed=False,
            )
        raise
    finally:
        if owns_client:
            await http.aclose()


def _number(row: dict[str, str], key: str, converter: type[int] | type[float]) -> int | float:
    raw = row.get(key, "0") or "0"
    try:
        return converter(raw)
    except ValueError:
        return converter(0)


def load_retail_stats(path: Path) -> dict[str, RetailKeywordStats]:
    """Load compact placement statistics keyed by normalized keyword."""
    output: dict[str, RetailKeywordStats] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            keyword = (row.get("keyword") or "").strip().lower()
            if not _KEYWORD_RE.fullmatch(keyword):
                continue
            placements: dict[str, PlacementStats] = {}
            for placement in _PLACEMENTS:
                placements[placement] = PlacementStats(
                    sale_count=int(_number(row, f"{placement}_sale_count", int)),
                    price_sum=int(_number(row, f"{placement}_price_sum", int)),
                    price_avg=float(_number(row, f"{placement}_price_avg", float)),
                    price_max=int(_number(row, f"{placement}_price_max", int)),
                )
            output[keyword] = RetailKeywordStats(keyword=keyword, placements=placements)
    return output


def _segmentations(sld: str, known: dict[str, RetailKeywordStats]) -> set[tuple[str, ...]]:
    """Return conservative English parses, not every possible CSV substring.

    Exhaustive substring splitting turns common fragments such as ``the`` into
    false demand. WordNinja's Wikipedia-frequency model provides one stable
    compound split; an exact whole-word parse is also allowed.
    """
    candidates: set[tuple[str, ...]] = set()
    if sld in known:
        candidates.add((sld,))
    split_words = cast("Callable[[str], list[str]]", wordninja.split)
    split = tuple(part.lower() for part in split_words(sld))
    if 1 <= len(split) <= 3 and all(len(part) >= 3 and part in known for part in split):
        candidates.add(split)
    return candidates


def find_market_evidence(
    domain: str, known: dict[str, RetailKeywordStats]
) -> MarketEvidence | None:
    """Choose the best one-to-three-word parse using observed retail sales."""
    sld = domain.rsplit(".", 1)[0].lower()
    candidates: list[tuple[float, MarketEvidence]] = []
    for terms in _segmentations(sld, known):
        if len(terms) == 1:
            placement_names = ("exact",)
        elif len(terms) == 2:
            placement_names = ("start", "end")
        else:
            placement_names = ("start", "middle", "end")
        rows: list[dict[str, object]] = []
        meaningful: list[PlacementStats] = []
        price_max = 0
        for term, placement in zip(terms, placement_names, strict=True):
            value = known[term].placements[placement]
            price_max = max(price_max, value.price_max)
            ignored = term in _MARKET_STOPWORDS
            if not ignored:
                meaningful.append(value)
            rows.append(
                {
                    "term": term,
                    "placement": placement,
                    "sale_count": value.sale_count,
                    "price_avg": value.price_avg,
                    "price_max": value.price_max,
                    "ignored_as_stopword": ignored,
                }
            )
        if not meaningful or any(value.sale_count <= 0 for value in meaningful):
            continue
        # Never add placement counts: the underlying sales sets can overlap.
        # The weakest meaningful term/placement is a conservative demand gate.
        sale_count_floor = min(value.sale_count for value in meaningful)
        price_avg_floor = min(value.price_avg for value in meaningful)
        ranking = math.log1p(sale_count_floor) * 10.0 + math.log1p(price_avg_floor)
        candidates.append(
            (
                ranking,
                MarketEvidence(
                    terms=terms,
                    sale_count_floor=sale_count_floor,
                    price_avg_floor=round(price_avg_floor, 2),
                    price_max=price_max,
                    placements=tuple(rows),
                ),
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -len(item[1].terms)), reverse=True)
    return candidates[0][1]
