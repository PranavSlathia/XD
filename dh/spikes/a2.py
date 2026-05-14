"""Phase 0.5 — A2 yield spike.

Sample 500–1,000 high-star GitHub repos, extract README/docs URLs (prose only,
no code blocks), classify context, normalize to eTLD+1, dedupe, run liveness +
RDAP, manually review top-50. Write the result to `docs/spikes/a2-yield.md`.

This module is the stub.  Implementation pending — must keep cost <$10 total.

Decision gate (PRD §8 Phase 0.5):
    ≥ 3 buyable+interesting in top-50  AND  ≥ 1 buyable/day projected
        → proceed to Phase 1 build
    Otherwise iterate path classifier / raise star floor / pivot methodology.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SpikeConfig:
    n_repos: int = 1000
    star_floor: int = 5000
    max_files_per_repo: int = 50
    max_md_files_per_repo: int = 30
    max_clone_mb: int = 50
    daily_url_cap: int = 50_000
    bq_max_bytes_billed: int = 10 * 1024**3      # 10 GB
    output_path: Path = field(
        default_factory=lambda: Path("docs/spikes/a2-yield.md")
    )


@dataclass
class SpikeResult:
    started_at: datetime
    finished_at: datetime | None = None
    repos_sampled: int = 0
    urls_extracted: int = 0
    urls_after_context_filter: int = 0
    distinct_registrable_domains: int = 0
    domains_nxdomain: int = 0
    domains_rdap_available: int = 0
    top50_buyable_interesting: int = 0   # operator-filled after manual review
    total_spend_usd: float = 0.0


async def run_a2_spike(cfg: SpikeConfig | None = None) -> SpikeResult:
    """Run the spike end-to-end.

    Pipeline (see PRD §8 Phase 0.5):
        1. Sample repos via GHArchive BigQuery (`gharchive.day.YYYYMMDD`,
           `maximum_bytes_billed=<cfg.bq_max_bytes_billed>`).
        2. For each repo, fetch README/docs markdown via GitHub Contents API
           with ETag conditional requests.
        3. Extract URLs from markdown PROSE (skip code blocks).
        4. Classify context via dh.sources.github.context.classify_url_context.
           Drop everything outside ACCEPTABLE_CONTEXTS.
        5. Normalize to registrable domain (eTLD+1) via tldextract.
        6. Liveness probe (httpx async) with concurrency limit.
        7. RDAP authoritative availability waterfall.
        8. Top-50 by max_source_authority + cited-url-count.
        9. Render `docs/spikes/a2-yield.md` for manual review.
    """
    cfg = cfg or SpikeConfig()
    started = datetime.utcnow()
    _ = cfg  # silence unused-warning until implemented
    raise NotImplementedError(
        "A2 spike harness is a stub. Implement after scaffold is committed and "
        ".env / Docker / ports on Dell are confirmed."
    )
