"""OpenPageRank Top-10-Million reference dataset.

The public CSV is refreshed per OpenPageRank release. We cache the 117 MiB ZIP
and stream it in rank order, stopping as soon as enough pending-delete matches
have been found or the configured authority floor has been crossed.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import os
import zipfile
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import httpx

from dh.logging import log

_DATASET_URL = "https://download.openpagerank.net/top10milliondomains.csv.zip"
_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
_MAX_CSV_BYTES = 1024 * 1024 * 1024


class TopDomainsSourceError(RuntimeError):
    """The reference download or CSV did not match its expected contract."""


@dataclass(frozen=True, slots=True)
class TopDomainsDataset:
    path: Path
    source_version: str
    refreshed: bool


@dataclass(frozen=True, slots=True)
class TopDomainRecord:
    domain: str
    rank: int
    open_pagerank: float
    referring_domains: int


def _validate_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
                raise TopDomainsSourceError("OpenPageRank archive must contain one CSV")
            if members[0].file_size > _MAX_CSV_BYTES:
                raise TopDomainsSourceError("OpenPageRank CSV exceeds the 1 GiB safety limit")
            with archive.open(members[0]) as stream:
                header = stream.readline().decode("utf-8-sig").strip()
            if header != "Rank,Domain,Extension,Open Page Rank,Referring Domains":
                raise TopDomainsSourceError("OpenPageRank CSV columns changed")
    except zipfile.BadZipFile as exc:
        raise TopDomainsSourceError("OpenPageRank response was not a valid ZIP") from exc


async def ensure_top_domains_dataset(
    data_dir: Path,
    *,
    refresh_after_days: int = 7,
    client: httpx.AsyncClient | None = None,
) -> TopDomainsDataset:
    """Return a validated local reference, refreshing it atomically when stale."""
    target_dir = data_dir / "reference"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "openpagerank-top10m.csv.zip"
    max_age = dt.timedelta(days=max(1, refresh_after_days))
    if target.exists():
        modified = dt.datetime.fromtimestamp(target.stat().st_mtime, tz=dt.UTC)
        if dt.datetime.now(dt.UTC) - modified < max_age:
            _validate_archive(target)
            return TopDomainsDataset(
                path=target,
                source_version=modified.date().isoformat(),
                refreshed=False,
            )

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=300, follow_redirects=True)
    temporary = target.with_suffix(".download")
    try:
        async with http.stream("GET", _DATASET_URL, timeout=300) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and int(declared) > _MAX_ARCHIVE_BYTES:
                raise TopDomainsSourceError("OpenPageRank archive exceeds 256 MiB")
            total = 0
            with temporary.open("wb") as output:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                    total += len(chunk)
                    if total > _MAX_ARCHIVE_BYTES:
                        raise TopDomainsSourceError("OpenPageRank archive exceeds 256 MiB")
                    output.write(chunk)
            source_version = (
                response.headers.get("last-modified")
                or response.headers.get("etag")
                or dt.date.today().isoformat()
            )
        _validate_archive(temporary)
        os.replace(temporary, target)
        return TopDomainsDataset(
            path=target,
            source_version=source_version,
            refreshed=True,
        )
    except Exception:
        if temporary.exists():
            temporary.unlink()
        if target.exists():
            log.warning("openpagerank.reference.refresh_failed_using_stale")
            _validate_archive(target)
            modified = dt.datetime.fromtimestamp(target.stat().st_mtime, tz=dt.UTC)
            return TopDomainsDataset(
                path=target,
                source_version=f"stale:{modified.date().isoformat()}",
                refreshed=False,
            )
        raise
    finally:
        if owns_client:
            await http.aclose()


def intersect_top_domains(
    dataset_path: Path,
    wanted_domains: Collection[str],
    *,
    min_open_pagerank: float,
    min_referring_domains: int,
    limit: int,
) -> list[TopDomainRecord]:
    """Return the highest-ranked wanted domains meeting the authority floors."""
    wanted = {d.lower() for d in wanted_domains}
    if not wanted or limit <= 0:
        return []
    matches: list[TopDomainRecord] = []
    with zipfile.ZipFile(dataset_path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) != 1:
            raise TopDomainsSourceError("OpenPageRank archive member count changed")
        with archive.open(members[0]) as raw:
            text_stream = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text_stream)
            for row in reader:
                try:
                    open_pagerank = float(row["Open Page Rank"])
                    referring_domains = int(row["Referring Domains"])
                    rank = int(row["Rank"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise TopDomainsSourceError("Invalid OpenPageRank CSV row") from exc
                if open_pagerank < min_open_pagerank:
                    break
                domain = row.get("Domain", "").lower()
                if domain not in wanted or referring_domains < min_referring_domains:
                    continue
                matches.append(
                    TopDomainRecord(
                        domain=domain,
                        rank=rank,
                        open_pagerank=open_pagerank,
                        referring_domains=referring_domains,
                    )
                )
                if len(matches) >= limit:
                    break
    return matches
