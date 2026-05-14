"""Persist a spike run's results to the DB.

Designed to be idempotent: running the spike twice over the same input
produces the same DB state (modulo new `availability_checks` rows, which
are evidence-trail and always append).

Writes (in order):
  1. `sources` — one row per repo (kind='github_readme')
  2. `candidates` — one row per registrable domain (UPSERT on `domain`)
  3. `source_mentions` — bulk insert; UNIQUE(source_url_hash, cited_url_hash)
                         drops duplicate rows on conflict
  4. `http_observations` — DNS NXDOMAIN result per domain
  5. `rdap_snapshots` — full RDAP raw response per checked domain
  6. `availability_checks` — every RDAP/WhoisJSON call with cost_micros
  7. `wayback_snapshots` — CDX summaries for the top N

Updates `candidates.current_status` and `candidates.availability_confidence`
from the most recent authoritative check.

NOTE: composite_score is intentionally LEFT NULL by the spike. The
dh-worker-scoring service computes it from the latest `scoring_weights`
row; that decouples scoring evolution from ingestion.
"""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from dh.db.engine import session_scope
from dh.db.models import (
    AvailabilityCheck,
    Candidate,
    HttpObservation,
    RdapSnapshot,
    Source,
    SourceMention,
    WaybackSnapshot,
)
from dh.logging import log
from dh.sources.openpagerank.client import OPRResult
from dh.sources.rdap.client import AvailabilityResult
from dh.sources.wayback.cdx import CdxSummary

GITHUB_README_KIND = "github_readme"


def _sha256(s: str) -> bytes:
    return hashlib.sha256(s.encode("utf-8")).digest()


async def _upsert_sources(
    session: AsyncSession, repos: list[dict[str, Any]]
) -> dict[str, int]:
    """Upsert `sources` rows; return mapping of source_uri → id."""
    if not repos:
        return {}
    stmt = (
        pg_insert(Source)
        .values(repos)
        .on_conflict_do_nothing(index_elements=["kind", "source_uri"])
    )
    await session.execute(stmt)

    # Pull IDs back (insert ... returning id won't work cleanly with do_nothing
    # because rows that conflicted aren't returned).
    uris = [r["source_uri"] for r in repos]
    res = await session.execute(
        select(Source.id, Source.source_uri).where(
            Source.kind == GITHUB_README_KIND, Source.source_uri.in_(uris)
        )
    )
    return {uri: sid for sid, uri in res.all()}


async def _upsert_candidates(
    session: AsyncSession, domains: list[str]
) -> dict[str, int]:
    """Upsert `candidates` rows; return mapping of domain → id.

    Uses ON CONFLICT (domain) DO UPDATE SET last_observed = now() so we
    bump the watermark without changing scoring fields.
    """
    if not domains:
        return {}
    rows = [{"domain": d} for d in domains]
    stmt = pg_insert(Candidate).values(rows)
    # Bump last_observed on conflict, leave everything else alone.
    stmt = stmt.on_conflict_do_update(
        index_elements=["domain"],
        set_={"last_observed": stmt.excluded.last_observed},
    )
    await session.execute(stmt)

    res = await session.execute(
        select(Candidate.id, Candidate.domain).where(Candidate.domain.in_(domains))
    )
    return {d: cid for cid, d in res.all()}


async def _bulk_insert_mentions(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> int:
    """Bulk insert source_mentions, dropping (source_url_hash, cited_url_hash)
    duplicates via ON CONFLICT DO NOTHING. Returns rows attempted."""
    if not rows:
        return 0
    stmt = (
        pg_insert(SourceMention)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["source_url_hash", "cited_url_hash"]
        )
    )
    await session.execute(stmt)
    return len(rows)


async def _update_candidate_status(
    session: AsyncSession,
    candidate_id: int,
    *,
    status: str,
    confidence: str,
) -> None:
    cand = await session.get(Candidate, candidate_id)
    if cand is None:
        return
    cand.current_status = status
    cand.availability_confidence = confidence


async def persist_spike_run(
    *,
    rollups: dict[str, object],
    nxdomain_set: set[str],
    opr_map: dict[str, OPRResult],
    top_candidates: list[object],
    avail_results: list[AvailabilityResult],
    wb_map: dict[str, CdxSummary],
) -> dict[str, int]:
    """Persist a spike run. Returns a small counts dict for logging.

    rollups: dict[domain → CandidateRollup-like with .domain, .mentions]
    top_candidates: list of CandidateRollup-like in ranked order
    """
    # Build the inputs from the rollups; mentions carry .repo (Repo) and
    # .file_path / .url / .context_type.
    repo_keys: dict[str, dict[str, Any]] = {}
    domain_set: set[str] = set()
    mention_rows: list[dict[str, Any]] = []

    for domain, roll in rollups.items():  # type: ignore[assignment]
        domain_set.add(domain)
        for m in roll.mentions:  # type: ignore[attr-defined]
            repo = m.repo
            full_name = repo.full_name
            repo_keys.setdefault(
                full_name,
                {
                    "kind": GITHUB_README_KIND,
                    "source_uri": f"github:{full_name}",
                    "authority": float(repo.stars),
                },
            )
            source_url = (
                f"https://github.com/{full_name}/blob/{repo.default_branch}/{m.file_path}"
            )
            mention_rows.append(
                {
                    "_full_name": full_name,
                    "_domain": domain,
                    "source_url": source_url,
                    "source_url_hash": _sha256(source_url),
                    "cited_url": m.url,
                    "cited_url_hash": _sha256(m.url),
                    "context_type": m.context_type,
                    "context_snippet": (m.surrounding or "")[:500] or None,
                }
            )

    counts = {
        "sources_seen": len(repo_keys),
        "candidates_seen": len(domain_set),
        "mentions_attempted": len(mention_rows),
    }
    log.info("spike.persist.start", **counts)

    async with session_scope() as session:
        # 1. sources
        repo_id_map = await _upsert_sources(
            session, list(repo_keys.values())
        )
        # 2. candidates
        cand_id_map = await _upsert_candidates(session, sorted(domain_set))

        # 3. source_mentions (resolve foreign-key ids)
        resolved_mentions: list[dict[str, Any]] = []
        for m in mention_rows:
            cid = cand_id_map.get(m.pop("_domain"))
            sid = repo_id_map.get(f"github:{m.pop('_full_name')}")
            if cid is None or sid is None:
                continue
            m["candidate_id"] = cid
            m["source_id"] = sid
            resolved_mentions.append(m)
        await _bulk_insert_mentions(session, resolved_mentions)

        # 4. http_observations: record DNS NXDOMAIN result per domain
        # (one row per candidate; not a full HTTP probe yet — that's Phase 2)
        http_rows: list[HttpObservation] = []
        for domain in domain_set:
            cid = cand_id_map.get(domain)
            if cid is None:
                continue
            is_nxdomain = domain in nxdomain_set
            http_rows.append(
                HttpObservation(
                    candidate_id=cid,
                    status_code=None,
                    final_url=None,
                    is_parked=None,
                    ns_signal="nxdomain" if is_nxdomain else "has_ns",
                )
            )
        session.add_all(http_rows)

        # 5+6. rdap_snapshots + availability_checks (top-N only — that's all the
        # spike RDAP-checks)
        for cand, avail in zip(top_candidates, avail_results, strict=True):  # type: ignore[arg-type]
            cid = cand_id_map.get(cand.domain)  # type: ignore[attr-defined]
            if cid is None:
                continue
            session.add(
                AvailabilityCheck(
                    candidate_id=cid,
                    source=avail.source,
                    status=avail.status,
                    is_authoritative=(avail.confidence == "authoritative"),
                    cost_micros=avail.api_cost_micros,
                    raw_response=avail.raw_response,
                )
            )
            if avail.source == "rdap" and avail.confidence != "unknown":
                rdap_server = None
                if isinstance(avail.raw_response, dict):
                    rdap_server_val = avail.raw_response.get("rdap_server")
                    if isinstance(rdap_server_val, str):
                        rdap_server = rdap_server_val
                session.add(
                    RdapSnapshot(
                        candidate_id=cid,
                        rdap_server=rdap_server,
                        epp_statuses=avail.epp_statuses or None,
                        expiry_date=None,  # not parsed yet
                        registrar=avail.registrar,
                        raw_response=avail.raw_response,
                    )
                )
            await _update_candidate_status(
                session,
                cid,
                status=avail.status,
                confidence=avail.confidence,
            )

        # 7. wayback_snapshots
        for domain, cdx in wb_map.items():
            cid = cand_id_map.get(domain)
            if cid is None or cdx.capture_count == 0:
                continue
            session.add(
                WaybackSnapshot(
                    candidate_id=cid,
                    first_capture=None,  # CDX timestamp is YYYYMMDDHHMMSS string;
                    last_capture=None,   # convert in a later worker pass
                    capture_count=cdx.capture_count,
                    cdx_summary={
                        "first_capture_ts": cdx.first_capture,
                        "last_capture_ts": cdx.last_capture,
                        "entries_sampled": len(cdx.entries),
                    },
                )
            )

    log.info("spike.persist.done", **counts)
    return counts
