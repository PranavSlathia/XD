"""Phase 0.5 — A2 yield spike.

End-to-end: sample 500–1,000 high-star repos → extract README/docs URLs (prose,
no code blocks) → classify context → normalize to eTLD+1 → dedupe → liveness +
RDAP → top-50 markdown report.

Decision gate (PRD §8 Phase 0.5):
    ≥ 3 buyable+interesting in top-50  AND  ≥ 1 buyable/day projected
        → proceed to Phase 1 build
    Otherwise iterate path classifier / raise star floor / pivot methodology.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import tldextract

from dh.logging import log
from dh.sources.github.contents import extract_urls_from_repo
from dh.sources.github.repos import ExtractedUrl, Repo
from dh.sources.github.search import sample_high_star_repos
from dh.sources.rdap.client import AvailabilityResult, check_availability
from dh.sources.wayback.cdx import CdxSummary, fetch_cdx


# --------------------------------------------------------------------------- #
# Config / result
# --------------------------------------------------------------------------- #

@dataclass
class SpikeConfig:
    n_repos: int = 500
    star_floor: int = 5000
    pushed_before: str | None = None  # e.g. "2022-01-01" for link-rot sampling
    extra_query: str | None = None    # raw GitHub-search qualifier, e.g. "awesome in:name"
    max_md_files_per_repo: int = 30
    daily_url_cap: int = 50_000
    extract_concurrency: int = 4
    rdap_concurrency: int = 4
    top_n_for_report: int = 50
    fetch_wayback_for_top: int = 30
    output_path: Path = field(
        default_factory=lambda: Path("docs/spikes/a2-yield.md")
    )


@dataclass
class CandidateRollup:
    """One registrable domain rolled up across all mentions."""

    domain: str
    mentions: list[ExtractedUrl] = field(default_factory=list)

    @property
    def n_mentions(self) -> int:
        return len(self.mentions)

    @property
    def distinct_sources(self) -> int:
        return len({m.repo.full_name for m in self.mentions})

    @property
    def max_source_authority(self) -> int:
        return max((m.repo.stars for m in self.mentions), default=0)

    @property
    def first_repo(self) -> Repo:
        return self.mentions[0].repo


@dataclass
class SpikeResult:
    started_at: datetime
    finished_at: datetime | None = None
    repos_sampled: int = 0
    repos_with_urls: int = 0
    urls_extracted: int = 0
    distinct_registrable_domains: int = 0
    domains_rdap_available: int = 0
    domains_rdap_authoritative: int = 0
    estimated_spend_usd: float = 0.0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_TLDX = tldextract.TLDExtract(cache_dir=None, suffix_list_urls=())


def registrable(url: str) -> str | None:
    """Return the registrable (eTLD+1) domain or None for invalid/IP/unsuffixed."""
    ext = _TLDX(url)
    if not ext.suffix or not ext.domain:
        return None
    return f"{ext.domain}.{ext.suffix}".lower()


def _shorten(s: str, n: int = 90) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #

async def _extract_repo(
    repo: Repo, *, max_md_files: int, sem: asyncio.Semaphore
) -> list[ExtractedUrl]:
    async with sem:
        try:
            return await extract_urls_from_repo(repo, max_md_files=max_md_files)
        except Exception as e:  # noqa: BLE001
            log.warning("spike.repo.error", repo=repo.full_name, error=str(e))
            return []


async def _check_domain(
    domain: str, *, sem: asyncio.Semaphore
) -> AvailabilityResult:
    async with sem:
        try:
            return await check_availability(domain)
        except Exception as e:  # noqa: BLE001
            log.warning("spike.rdap.error", domain=domain, error=str(e))
            from dh.sources.rdap.client import AvailabilityResult as _AR

            return _AR(
                domain=domain,
                status="unknown",
                confidence="unknown",
                source="rdap",
                raw_response={"error": str(e)},
            )


async def _fetch_wayback(
    domain: str, *, sem: asyncio.Semaphore
) -> CdxSummary:
    async with sem:
        try:
            return await fetch_cdx(domain)
        except Exception as e:  # noqa: BLE001
            log.warning("spike.wayback.error", domain=domain, error=str(e))
            return CdxSummary(domain=domain)


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #

def render_report(
    cfg: SpikeConfig,
    result: SpikeResult,
    top: list[tuple[CandidateRollup, AvailabilityResult, CdxSummary | None]],
) -> str:
    lines: list[str] = []
    lines.append("# A2 Phase 0.5 yield spike\n")
    lines.append(
        f"Run started {result.started_at.isoformat(timespec='seconds')}, "
        f"finished {(result.finished_at or datetime.utcnow()).isoformat(timespec='seconds')}.\n"
    )
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Repos sampled: **{result.repos_sampled}** (star floor: {cfg.star_floor})")
    lines.append(f"- Repos that yielded URLs: **{result.repos_with_urls}**")
    lines.append(f"- Acceptable URLs extracted (after path/context filter): **{result.urls_extracted}**")
    lines.append(f"- Distinct registrable domains: **{result.distinct_registrable_domains}**")
    lines.append(f"- Domains RDAP-checked authoritatively: **{result.domains_rdap_authoritative}**")
    lines.append(f"- Domains marked **available** by RDAP: **{result.domains_rdap_available}**")
    lines.append(f"- Estimated spend: **${result.estimated_spend_usd:.2f}**")
    lines.append("")

    lines.append("## Decision gate (PRD §8 Phase 0.5)")
    lines.append("")
    lines.append(f"Top-{cfg.top_n_for_report} below. Operator: review the table,")
    lines.append("mark buyable+interesting domains, and fill in the count.")
    lines.append("")
    lines.append("- [ ] Buyable+interesting count in top-50: ____")
    lines.append("- [ ] Projected buyable/day at scale: ____")
    lines.append("")
    lines.append("Pass gate: ≥3 buyable+interesting AND ≥1/day projected → proceed to Phase 1 build.")
    lines.append("")

    lines.append("## Top candidates (ranked by max_source_authority × n_mentions)")
    lines.append("")
    lines.append("| # | Domain | Available? | Stars (max) | Mentions | Sources | Wayback | First repo / file |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for i, (cand, avail, cdx) in enumerate(top, start=1):
        repo_label = cand.first_repo.full_name
        path = cand.mentions[0].file_path
        if avail.status == "available":
            avail_label = "✅ available"
        elif avail.status in ("pending_delete", "redemption_period", "expiring_soon"):
            avail_label = f"⏳ {avail.status}"
        else:
            avail_label = f"❌ {avail.status}"
        wb_label = "—"
        if cdx and cdx.capture_count:
            wb_label = f"{cdx.capture_count} captures · {cdx.first_capture[:4]}–{cdx.last_capture[:4]}"
        lines.append(
            f"| {i} | `{_shorten(cand.domain, 40)}` | {avail_label} | "
            f"{cand.max_source_authority:,} | {cand.n_mentions} | "
            f"{cand.distinct_sources} | {wb_label} | "
            f"`{_shorten(repo_label, 30)}` · `{_shorten(path, 25)}` |"
        )
    lines.append("")

    lines.append("## Mention detail (first 100 candidates)")
    lines.append("")
    for cand, avail, _ in top[:100]:
        lines.append(f"### `{cand.domain}` — {avail.status} ({avail.confidence})")
        for m in cand.mentions[:5]:
            lines.append(
                f"- `{m.repo.full_name}` ⭐{m.repo.stars:,} · `{m.file_path}` · {m.context_type}"
            )
            lines.append(f"  - URL: <{m.url}>")
        if len(cand.mentions) > 5:
            lines.append(f"- _… {len(cand.mentions) - 5} more mentions_")
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #

async def run_a2_spike(cfg: SpikeConfig | None = None) -> SpikeResult:
    cfg = cfg or SpikeConfig()
    result = SpikeResult(started_at=datetime.utcnow())

    log.info(
        "spike.a2.sample.start",
        n=cfg.n_repos,
        star_floor=cfg.star_floor,
        pushed_before=cfg.pushed_before,
        extra_query=cfg.extra_query,
    )
    repos = await sample_high_star_repos(
        n=cfg.n_repos,
        star_floor=cfg.star_floor,
        pushed_before=cfg.pushed_before,
        extra_query=cfg.extra_query,
    )
    result.repos_sampled = len(repos)
    log.info("spike.a2.sample.done", got=len(repos))

    extract_sem = asyncio.Semaphore(cfg.extract_concurrency)
    extracts: list[list[ExtractedUrl]] = await asyncio.gather(
        *(_extract_repo(r, max_md_files=cfg.max_md_files_per_repo, sem=extract_sem) for r in repos),
        return_exceptions=False,
    )

    rollups: dict[str, CandidateRollup] = {}
    total_urls = 0
    repos_with_urls = 0
    for repo_urls in extracts:
        if not repo_urls:
            continue
        repos_with_urls += 1
        for eu in repo_urls:
            if total_urls >= cfg.daily_url_cap:
                break
            total_urls += 1
            d = registrable(eu.url)
            if not d:
                continue
            roll = rollups.setdefault(d, CandidateRollup(domain=d))
            roll.mentions.append(eu)
        if total_urls >= cfg.daily_url_cap:
            log.warning("spike.a2.cap_hit", cap=cfg.daily_url_cap)
            break

    result.urls_extracted = total_urls
    result.repos_with_urls = repos_with_urls
    result.distinct_registrable_domains = len(rollups)
    log.info(
        "spike.a2.extract.done",
        urls=total_urls,
        domains=len(rollups),
        repos_with_urls=repos_with_urls,
    )

    # Rank candidates BEFORE we spend on RDAP — only check the top.
    ranked = sorted(
        rollups.values(),
        key=lambda c: (c.max_source_authority * c.n_mentions, c.distinct_sources),
        reverse=True,
    )
    top = ranked[: cfg.top_n_for_report]
    log.info("spike.a2.rdap.start", n=len(top))

    rdap_sem = asyncio.Semaphore(cfg.rdap_concurrency)
    avail_results: list[AvailabilityResult] = await asyncio.gather(
        *(_check_domain(c.domain, sem=rdap_sem) for c in top),
    )

    auth_count = sum(1 for a in avail_results if a.confidence == "authoritative")
    avail_count = sum(1 for a in avail_results if a.status == "available")
    spend_micros = sum(a.api_cost_micros for a in avail_results)
    result.domains_rdap_authoritative = auth_count
    result.domains_rdap_available = avail_count
    result.estimated_spend_usd = spend_micros / 1_000_000

    # Wayback for the top N (operator review aid only).
    wb_targets = [c for c, a in zip(top, avail_results, strict=True)][: cfg.fetch_wayback_for_top]
    log.info("spike.a2.wayback.start", n=len(wb_targets))
    wb_sem = asyncio.Semaphore(4)
    wb_results = await asyncio.gather(
        *(_fetch_wayback(c.domain, sem=wb_sem) for c in wb_targets),
    )
    wb_map = {c.domain: w for c, w in zip(wb_targets, wb_results, strict=True)}

    triples: list[tuple[CandidateRollup, AvailabilityResult, CdxSummary | None]] = []
    for cand, avail in zip(top, avail_results, strict=True):
        triples.append((cand, avail, wb_map.get(cand.domain)))

    cfg.output_path.parent.mkdir(parents=True, exist_ok=True)
    result.finished_at = datetime.utcnow()
    cfg.output_path.write_text(render_report(cfg, result, triples))
    log.info(
        "spike.a2.done",
        urls=total_urls,
        domains=len(rollups),
        available=avail_count,
        report=str(cfg.output_path),
        spend_usd=f"{result.estimated_spend_usd:.2f}",
    )
    return result
