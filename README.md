# Domain Hunter

XD is an always-on, evidence-first research system for `.com`, `.net`, `.org`,
`.co`, `.io`, and `.ai`. It evaluates commercially strong **Name Assets** and
verified-link **Authority Assets** independently; a Hybrid passes both. It does
**not** buy, bid, backorder, register, list, contact, or spend.

Repo `PranavSlathia/XD`, deployed at `~/docker/domain-hunter/` on Dell
`100.103.66.92`. The API binds to localhost on port `8007`. The private macOS
client lives at `apps/macos/XD`; Vulture remains during a minimum 14-day parity
period. There is no public dashboard.

## What runs by default

`docker compose up -d` starts:

- `dh-pg` and `dh-redis` — isolated state on localhost ports `5436` and `6381`.
- `dh-api` — read/review API on localhost port `8007`.
- `dh-worker-inventory` — six-hour pending-delete inventory cycle.
- `dh-worker-rdap` — authoritative registration-state confirmation.
- `dh-worker-wayback` — archive-history metadata for active candidates.
- `dh-worker-scoring` — legacy candidate score maintenance.
- `dh-worker-operator` — low-concurrency, typed jobs and bounded content crawls.
- `vulture` — Discord commands and a daily research digest when configured.

GitHub discovery is permanently retired; historical evidence remains. Read-only
registrar quotes are available through the `hand-registration` profile and typed
availability jobs. The dead Redis scheduler is gone.

## XD pipeline

1. Normalize observations from full expiry inventory and allowlisted content
   sources.
2. Run cheap independent Name and Authority screens. The complete inventory is
   screened for names before any authority intersection.
3. Promote only observations that clear at least one lane's first-stage screen.
4. Collect expensive evidence for the bounded best subset: name demand/comps or
   directly verified referring pages.
5. Apply versioned lane and shared gates, including rights/history/reputation and
   authoritative registrar availability with a current standard-price quote.
6. Generate lane-specific dossiers. A language model can explain evidence but
   cannot promote a domain.
7. Surface Research, Ready, or Reject for append-only human review; store later
   commercial outcomes for calibration.

Research is deliberately incomplete. Ready remains blocked until the selected
lane's evidence and every shared gate pass, including:

- archive content review;
- independent backlink/profile review;
- trademark and former-brand clearance;
- domain-specific comparable sales;
- a credible end-user buyer thesis; and
- a current normal-price registrar quote.

Authority is not name quality, name quality does not require backlinks, and no
automated state is permission to acquire.

## API

Device-authenticated API v1 includes Today, lane-filtered candidates, guarded
reviews, SSE events/global read receipts, runs/workers, typed jobs, versioned
configuration, pairing/revocation, dossiers, and commercial outcomes under
`/api/v1`. Run `GET /openapi.json` for the exact schemas.

Legacy migration endpoints remain available:

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

- `docs/XD-PRD.md` — current product and rollout source of truth.
- `docs/ALWAYS_ON_PIPELINE.md` — historical deployed pipeline retained for
  migration/parity.
- `docs/CANDIDATE_REVIEW-2026-08-20.md` — first real-feed validation and manual
  accept/reject record.
- `docs/CZDS_APPLICATIONS.md` — truthful CZDS use guidance; never misrepresent a
  commercial acquisition purpose as non-commercial research.
- `CLAUDE.md` — engineering and Dell isolation rules.

The older PRD, research dossier, tech-stack log, and implementation audit are
historical records. Where they conflict, `docs/XD-PRD.md` wins.
