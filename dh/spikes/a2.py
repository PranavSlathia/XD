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
from dh.persistence.spike import persist_spike_run
from dh.sources.openpagerank.client import OPRResult, fetch_open_pagerank
from dh.sources.rdap.client import AvailabilityResult, check_availability, dns_is_nxdomain
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
    dns_concurrency: int = 20         # DNS is cheap; high concurrency OK
    rdap_concurrency: int = 4
    top_n_for_report: int = 50
    fetch_wayback_for_top: int = 30
    persist: bool = True
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
    domains_dns_checked: int = 0
    domains_nxdomain: int = 0
    domains_opr_fetched: int = 0
    domains_with_opr: int = 0
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


async def _dns_check(
    domain: str, *, sem: asyncio.Semaphore
) -> tuple[str, bool]:
    """Returns (domain, is_nxdomain)."""
    async with sem:
        try:
            return domain, await dns_is_nxdomain(domain)
        except Exception as e:  # noqa: BLE001
            log.debug("spike.dns.error", domain=domain, error=str(e))
            return domain, False


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
    *,
    opr_map: dict[str, OPRResult] | None = None,
) -> str:
    opr_map = opr_map or {}
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
    lines.append(f"- Domains DNS-checked: **{result.domains_dns_checked}**")
    lines.append(f"- Domains with NXDOMAIN (deadness hint, NOT availability): **{result.domains_nxdomain}**")
    lines.append(f"- Domains Open-PageRank-fetched: **{result.domains_opr_fetched}**")
    lines.append(f"- Domains with OPR > 0 (have real inbound authority): **{result.domains_with_opr}**")
    lines.append(f"- Domains RDAP-checked authoritatively (on NXDOMAIN survivors only): **{result.domains_rdap_authoritative}**")
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

    lines.append("## Top candidates (ranked by Open PageRank, then source authority)")
    lines.append("")
    lines.append("| # | Domain | Available? | OPR | Stars (max) | Mentions | Sources | Wayback | First repo / file |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
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
        opr_info = opr_map.get(cand.domain)
        if opr_info and opr_info.found and opr_info.page_rank_decimal:
            opr_label = f"{opr_info.page_rank_decimal:.2f}"
        else:
            opr_label = "—"
        lines.append(
            f"| {i} | `{_shorten(cand.domain, 40)}` | {avail_label} | "
            f"{opr_label} | "
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

    # --- DNS PRE-FILTER (free, fast) over ALL distinct domains ---
    # We're hunting for DEAD domains: most extracted URLs go to live, popular
    # destinations (github.com, arxiv.org, …). DNS NXDOMAIN is a cheap signal
    # that a domain is worth a paid availability check. Live domains are
    # filtered out here.
    all_domains = list(rollups.keys())
    log.info("spike.a2.dns.start", n=len(all_domains))
    dns_sem = asyncio.Semaphore(cfg.dns_concurrency)
    dns_results = await asyncio.gather(
        *(_dns_check(d, sem=dns_sem) for d in all_domains),
    )
    nxdomain_set = {d for d, is_nx in dns_results if is_nx}
    result.domains_dns_checked = len(all_domains)
    result.domains_nxdomain = len(nxdomain_set)
    log.info(
        "spike.a2.dns.done",
        checked=len(all_domains),
        nxdomain=len(nxdomain_set),
    )

    # Now rank ONLY the NXDOMAIN survivors.
    # (Falls back to all domains if zero NXDOMAIN — keeps the report informative
    #  rather than empty.)
    survivors = [r for r in rollups.values() if r.domain in nxdomain_set]
    if not survivors:
        log.warning("spike.a2.dns.no_survivors", note="ranking all domains as fallback")
        survivors = list(rollups.values())

    # --- OPEN PAGERANK ENRICHMENT ---
    # The linking repo's stars are a "who points at this" signal. They do NOT
    # convey backlink authority to the target domain. For resale, what matters
    # is the target domain's OWN inbound-link profile. DomCop Open PageRank
    # is a free, CC-derived 0–10 score — exactly the DA-proxy we need to filter
    # out domains with no real backlink authority before ranking.
    log.info("spike.a2.opr.start", n=len(survivors))
    opr_batch = await fetch_open_pagerank([s.domain for s in survivors])
    opr_map: dict[str, OPRResult] = {o.domain: o for o in opr_batch.results}
    domains_with_opr = sum(
        1
        for o in opr_batch.results
        if o.found and (o.page_rank_decimal or 0) > 0
    )
    result.domains_opr_fetched = len(opr_batch.results)
    result.domains_with_opr = domains_with_opr
    log.info(
        "spike.a2.opr.done",
        fetched=len(opr_batch.results),
        with_pagerank=domains_with_opr,
    )

    def _opr_score(c: CandidateRollup) -> float:
        opr = opr_map.get(c.domain)
        if not opr or not opr.found:
            return 0.0
        return float(opr.page_rank_decimal or 0)

    # Rank by (OPR, then source authority, then diversity, then mentions).
    # OPR is the dominant signal: a domain with OPR=0 is not worth a buy-decision
    # regardless of how many high-star READMEs mention it.
    ranked = sorted(
        survivors,
        key=lambda c: (
            _opr_score(c),
            c.max_source_authority,
            c.distinct_sources,
            c.n_mentions,
        ),
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
    cfg.output_path.write_text(render_report(cfg, result, triples, opr_map=opr_map))

    if cfg.persist:
        try:
            await persist_spike_run(
                rollups=rollups,
                nxdomain_set=nxdomain_set,
                opr_map=opr_map,
                top_candidates=top,
                avail_results=avail_results,
                wb_map=wb_map,
            )
        except Exception as e:  # noqa: BLE001
            log.error("spike.a2.persist.error", error=str(e))
    log.info(
        "spike.a2.done",
        urls=total_urls,
        domains=len(rollups),
        available=avail_count,
        report=str(cfg.output_path),
        spend_usd=f"{result.estimated_spend_usd:.2f}",
    )
    return result
