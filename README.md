# Domain Hunter

Always-on, evidence-first research pipeline for expiring `.com` domains. It
continuously narrows public pending-delete inventory to a small queue that is
worth human diligence. It does **not** buy, bid, backorder, list, or contact
anyone.

Repo `PranavSlathia/XD`, deployed at `~/docker/domain-hunter/` on Dell
`100.103.66.92`. The API binds to localhost on port `8007`; Vulture is the
optional Discord operator surface. There is intentionally no public dashboard.

## What runs by default

`docker compose up -d` starts:

- `dh-pg` and `dh-redis` — isolated state on localhost ports `5436` and `6381`.
- `dh-api` — read/review API on localhost port `8007`.
- `dh-worker-inventory` — six-hour pending-delete inventory cycle.
- `dh-worker-rdap` — authoritative registration-state confirmation.
- `dh-worker-wayback` — archive-history metadata for active candidates.
- `dh-worker-scoring` — legacy candidate score maintenance.
- `vulture` — Discord commands and a daily research digest when configured.

The old GitHub miner and LLM classifier are available only through the
`experimental` Compose profile. Hand-registration quotes are in the
`hand-registration` profile. The dead Redis scheduler is gone; every active
worker owns its own bounded loop.

## Current pipeline

1. Download DropCatch's public five-day pending-delete feed every six hours.
2. Keep clean alphabetic `.com` names of practical length.
3. Intersect them locally with the cached OpenPageRank Top-10-Million dataset.
4. Join NameBio's free, attribution-required RetailStats data. Compound names
   use a conservative word split and the weakest relevant keyword placement;
   overlapping sales are never added together.
5. Detect suspicious batches with near-identical authority metrics.
6. Prioritize the bounded public price/deadline lookups by market evidence,
   anomaly status, and score—not raw PageRank alone.
7. Persist the listing, provenance, source version, run metrics, and separate
   authority, resale, risk, confidence, and overall scores.
8. Confirm status through RDAP and collect Wayback metadata.
9. Surface `research`, `observe`, or `reject`. Only a human can turn research
   into an acquisition decision.

An automatic `research` verdict is deliberately incomplete. The following
remain mandatory before spending money:

- archive content review;
- independent backlink/profile review;
- trademark and former-brand clearance;
- domain-specific comparable sales;
- a credible end-user buyer thesis; and
- an operator-set maximum bid.

Authority is not resale value, a pending-delete listing is not guaranteed
availability, and an automated score is never permission to acquire.

## API

- `GET /health` — DB and Redis liveness.
- `GET /api/pipeline/status` — latest run and funnel counts.
- `GET /api/opportunities?verdict=research` — active, actionable evidence-backed
  queue. Pass `actionable_only=false` to audit manually closed candidates.
- `GET /api/candidates` and `GET /api/candidates/{domain}` — candidate history.
- `GET /api/digest/today` — research queue prepared for an agent/Discord digest.
- `POST /api/decisions` — append a human outcome; `passed`, `bought`, and
  `lost_to_other` leave the actionable queue, while a later `watching` decision
  reopens it. This performs no marketplace action.
- `GET|POST /api/scoring-weights` — legacy score configuration.

## Setup and checks

```bash
uv sync --extra dev
uv run ruff check .
uv run basedpyright dh tests
uv run pytest -q

uv run alembic upgrade head
docker compose config --services
docker compose up -d
curl -fsS http://127.0.0.1:8007/api/pipeline/status
```

Copy `.env.example` to `.env` and set `DH_DB_PASSWORD`. The always-on inventory
path needs no marketplace credentials. Discord needs its bot/channel settings;
the new OpenPageRank API key is optional enrichment. Secrets and downloaded
reference data stay outside Git.

## Durable docs

- `docs/ALWAYS_ON_PIPELINE.md` — current product contract, operations, evidence
  gates, failure modes, and upgrade path.
- `docs/CANDIDATE_REVIEW-2026-08-20.md` — first real-feed validation and manual
  accept/reject record.
- `docs/CZDS_APPLICATIONS.md` — truthful CZDS use guidance; never misrepresent a
  commercial acquisition purpose as non-commercial research.
- `CLAUDE.md` — engineering and Dell isolation rules.

The older PRD, research dossier, tech-stack log, and implementation audit are
historical design records. Where they conflict with the current pipeline, this
README and `docs/ALWAYS_ON_PIPELINE.md` win.
