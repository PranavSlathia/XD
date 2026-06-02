# Domain Hunter

Expired-domain discovery and scoring backend with a Discord operator surface. Domain Hunter no longer owns a web frontend. Human operators use Vulture slash commands in Discord; the Quip/Codex/Gemini agent layer can also call the FastAPI surface directly.

Repo `PranavSlathia/XD`, deployed at `~/docker/domain-hunter/` on Dell `100.103.66.92`.

## Scope

Domain Hunter autonomously discovers, enriches, scores, and exposes domain candidates. It does not handle acquisition, listing, resale, or a web dashboard.

Operator and agent surfaces:

- **Vulture** — Discord slash-command operator UI (`vulture`, `dh.bot`).
- **FastAPI** — thin programmatic API for Quip/Codex/Gemini and automation.

API endpoints:

- `GET /health` — DB and Redis liveness
- `GET /api/candidates` — ranked candidate list
- `GET /api/candidates/{domain}` — detail plus evidence trail
- `POST /api/decisions` — record agent/operator outcome
- `GET /api/scoring-weights` — current scoring weights
- `POST /api/scoring-weights` — create a new scoring version and invalidate scores
- `GET /api/digest/today` — high-confidence buyable shortlist for the agent layer

There is intentionally no `/api/events` SSE route and no DH web UI.

## Runtime model

`docker compose up -d` runs the backend stack:

- `dh-pg` — Postgres 16 + pgvector
- `dh-redis` — cap counters and worker signaling
- `dh-api` — FastAPI programmatic API
- `vulture` — Discord slash-command operator surface
- `dh-scheduler` — autonomous cron trigger publisher
- `dh-worker-a2` — GitHub README ingest
- `dh-worker-rdap` — RDAP / paid availability waterfall
- `dh-worker-wayback` — CDX history enrichment
- `dh-worker-classifier` — classifier transport, stub by default
- `dh-worker-scoring` — composite score persistence
- `dh-worker-registrar` — registrar quote lookup before digest eligibility

There is intentionally no `dh-web` service, no `web/` source tree, and no web healthcheck.

## Pipeline

1. **A2 ingest** — GitHub README mining with star floor, pushed-before gate, URL/path/context safety filters.
2. **Availability** — DNS is a hint only; RDAP / paid waterfalls set authoritative availability.
3. **Authority** — Open PageRank enrichment separates real link authority from nofollow README noise.
4. **Wayback** — CDX snapshot metadata and classifier evidence.
5. **Registrar quote** — purchasability and premium ceiling checks before digest eligibility.
6. **Scoring** — composite score with hard filters and persisted explanation fields.
7. **Operator review** — Vulture slash commands and agent API calls inspect, shortlist, and record outcomes.

## Scoring

Authority-first weights, OPR-dominant. GitHub README links are usually `rel="nofollow ugc"`, so source popularity is useful context but not equivalent to followed PageRank.

```text
open_pagerank_score      0.45
availability_score       0.15
referring_domains_score  0.10
wayback_clean_score      0.10
age_score                0.10
max_source_authority     0.05
source_diversity_bonus   0.05
spam_penalty            -0.10
tm_risk_penalty         -0.10
reputation_penalty      -0.10
```

Hard filters include `spam_history`, `not_available`, `premium_quote`, `tm_risk`, and `low_authority`.

## Architecture invariants

1. **MOC isolation.** `dh-*` names, `dh-net` network, ports `5436/6381`. Never touch `~/docker/moc/` or port `6380`.
2. **No web frontend.** `web/`, `dh-web`, and web-only API surfaces stay removed.
3. **Vulture stays.** Discord slash commands are the DH-owned operator surface.
4. **DNS NXDOMAIN is not availability.** Only authoritative availability sources gate the digest.
5. **A2 path/context classifier is the safety boundary.** Operational URLs, package manifests, workflows, code fences, vendored paths, and assets are rejected.
6. **Deadness-first ranking.** Live mega-domains must never reach the shortlist.

## Quick reference

```bash
# Setup
uv sync --extra dev

# Quality gates
uv run ruff check dh tests
uv run basedpyright dh tests
uv run pytest tests/ -q

# CLI
uv run dh --help
uv run dh db check
uv run dh spike a2 --no-dry-run --n-repos 500

# Alembic
uv run alembic upgrade head

# Backend stack: API + Vulture + scheduler + workers + DB/Redis
docker compose up -d
```

## Required env

```text
DH_DB_PASSWORD=...
DH_GITHUB_TOKEN=...                  # A2 ingest, read-only
DH_OPENPAGERANK_API_KEY=...          # DomCop OPR
DH_WHOISJSON_API_KEY=...             # authoritative availability fallback
DH_PORKBUN_API_KEY=...               # registrar quote lookup
DH_PORKBUN_SECRET_API_KEY=...
DH_DISCORD_BOT_TOKEN=...             # Vulture slash-command bot
DH_DISCORD_GUILD_ID=...
DH_DISCORD_CHANNEL_ID=...
DH_DISCORD_OWNER_ID=...
DH_SENTRY_DSN=...                    # GlitchTip-compatible, optional
DH_DIGEST_MIN_SCORE=40
DH_OPR_MIN_AUTHORITY=3.0
```

See `dh/config.py` for worker tunables, batch sizes, intervals, and spend caps.

## Docs

- `docs/PRD.md` — product requirements
- `docs/TECH_STACK.md` — locked technical decisions
- `docs/RESEARCH.md` — methodology research and repo audit
- `docs/IMPLEMENTATION_NOTES.md` — per-repo and per-API audit
- `docs/CZDS_APPLICATIONS.md` — zone-file access template
- `docs/spikes/` — Phase 0.5 yield-spike outputs
- `CLAUDE.md` — developer guide for Claude Code sessions
