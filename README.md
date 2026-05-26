# Domain Hunter

Self-hosted expired-domain discovery + scoring pipeline. Personal use, Tailscale-only. Repo `PranavSlathia/XD`, deployed at `~/docker/domain-hunter/` on Dell `100.103.66.92`.

**Scope:** ingest authority-graph citations → filter for dead/available → enrich → score → daily ranked shortlist. Acquisition + flipping handled separately by the operator.

## Status

**Live.** Full pipeline running on the Dell; CI deploys on push to `main` via a self-hosted GitHub Actions runner.

Pipeline stages (each is its own worker, communicates via Postgres + Redis):
1. **A2** — GitHub README ingest (`dh-worker-a2`). Star-floored, pushed-before-gated, path/context-safety filtered.
2. **DNS** — NXDOMAIN hint only; not authoritative.
3. **OPR** — Open PageRank enrichment for NXDOMAIN survivors (`dh-worker-rdap` chain).
4. **RDAP** — authoritative availability check for survivors.
5. **Wayback** — CDX snapshot + content classification.
6. **Scoring** — composite score v3 (`dh-worker-scoring`).
7. **Digest** — daily Discord webhook for survivors above threshold (`dh-scheduler`).

## Scoring (v3)

Authority-first weights, OPR-dominant. Lesson from first real ingest: **GitHub README links are `rel="nofollow ugc"`**, so `max_source_authority` (repo stars) is noise — those links don't pass PageRank. OPR is the real backlink-authority signal because PageRank only flows through followed links.

```
open_pagerank_score      0.45   (dominant)
availability_score       0.15   (deadness-aware: authoritative+available=100, etc.)
referring_domains_score  0.10
wayback_clean_score      0.10
age_score                0.10
max_source_authority     0.05   (nofollow noise — kept small)
source_diversity_bonus   0.05
spam_penalty            -0.10
tm_risk_penalty         -0.10
reputation_penalty      -0.10
```

Hard filters: `spam_history`, `not_available`, `premium_quote`, `tm_risk`, `low_authority` (confirmed-available but OPR < `DH_OPR_MIN_AUTHORITY`, default 3.0).

## Architecture invariants

1. **MOC isolation.** `dh-*` names, `dh-net` network, ports `5436/6381`. Never touch `~/docker/moc/` or port 6380.
2. **DNS NXDOMAIN is a hint, not availability.** Only RDAP / WhoisJSON / WhoisFreaks set `is_authoritative = true`.
3. **A2 path/context classifier is the safety boundary.** Rejects URLs from `requirements.txt`, workflows, code fences, asset hosts, etc. Registering an operational URL = supply-chain attack surface. 36 parametrised tests guard the rule set.
4. **Deadness-first ranking.** Rank only NXDOMAIN survivors. Live mega-domains (github.com, npmjs.com) must never reach the shortlist.
5. **Classifier transport behind `ClassifierClient` ABC.** Codex CLI is the locked transport.

## Docs

- `docs/PRD.md` — product requirements (§12 data model is canonical)
- `docs/TECH_STACK.md` — every locked technical decision
- `docs/RESEARCH.md` — methodology research + repo audit
- `docs/IMPLEMENTATION_NOTES.md` — per-repo + per-API audit
- `docs/CZDS_APPLICATIONS.md` — zone-file access application template
- `docs/spikes/` — Phase 0.5 yield-spike outputs
- `CLAUDE.md` — developer guide for Claude Code sessions

## Quick reference

```bash
# Setup
uv sync --extra dev

# Tests
uv run pytest tests/ -q                  # unit (deterministic)
uv run pytest tests/ -m integration      # testcontainers-Postgres

# Lint + types
uv run ruff check dh tests
uv run basedpyright dh tests

# CLI
uv run dh --help
uv run dh db check
uv run dh spike a2 --no-dry-run --n-repos 500

# Alembic
uv run alembic upgrade head

# Local stack
docker compose --profile all up -d
```

## Required env (`.env`)

```
DH_DB_PASSWORD=...
DH_GITHUB_TOKEN=...                  # A2 ingest (read-only)
DH_OPENPAGERANK_API_KEY=...          # DomCop OPR
DH_WHOISJSON_API_KEY=...             # authoritative availability
DH_DISCORD_WEBHOOK_URL=...           # daily digest
DH_SENTRY_DSN=...                    # GlitchTip (Sentry-compatible)
DH_DIGEST_MIN_SCORE=40
DH_OPR_MIN_AUTHORITY=3.0
```

See `dh/config.py` for the full settings surface (worker tunables, batch sizes, intervals, spend caps).
