# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

XD — a self-hosted, always-on domain-research engine with independent Name and
Authority Asset lanes plus a private SwiftUI macOS client. A Hybrid passes both
lanes independently; there is no compensating overall score. XD never bids,
buys, backorders, registers, lists, contacts, or spends. Personal-use,
localhost/Tailscale-only. Repo: `PranavSlathia/XD`
(deployed at `~/docker/domain-hunter/` on Dell `100.103.66.92`).

Read these before any non-trivial change:
- `docs/XD-PRD.md` — current product, evidence, safety, client, and rollout contract
- `docs/ALWAYS_ON_PIPELINE.md` — deployed legacy pipeline retained for parity
- `README.md` — current service topology and API
- `docs/CANDIDATE_REVIEW-2026-08-20.md` — real-feed validation baseline
- `docs/PRD.md`, `TECH_STACK.md`, `RESEARCH.md`, and `IMPLEMENTATION_NOTES.md` — historical records only

## Commands

```bash
# Setup (uv is the package manager)
uv sync --extra dev                # install all deps including test/lint tools

# Tests — unit-only by default
uv run pytest tests/ -q            # ~50 unit tests, all deterministic
uv run pytest tests/test_<file>.py # one file
uv run pytest tests/ -m integration  # testcontainers-Postgres tests (need Docker)

# Lint + type-check
uv run ruff check dh tests          # lint
uv run ruff format dh tests         # format
uv run basedpyright dh tests        # strict-mode type check

# CLI (Typer)
uv run dh --help
uv run dh device pairing-code --ttl-minutes 10
uv run dh db check
uv run dh score normalize-demo

# Run a single test
uv run pytest tests/test_lanes.py -v

# Alembic
uv run alembic revision --autogenerate -m "<change>"
uv run alembic upgrade head
```

## CI / Deploy

`.github/workflows/build.yml` runs on a **self-hosted GitHub Actions runner on the Dell** (systemd unit `actions.runner.PranavSlathia-XD.dh-dell`). Every relevant push to `main` runs unit and real-Postgres integration tests, backs up the Domain Hunter database, applies migrations, rebuilds the shared Python image, and reconciles the default Domain Hunter stack.

The runner survives reboots. Workflow is guarded with `if: github.repository == 'PranavSlathia/XD' && github.event_name != 'pull_request'` because the repo is public — fork PRs cannot execute the runner.

## Architecture invariants (do not violate)

1. **Server isolation is non-negotiable.** Domain Hunter uses `dh-*` container
   names, `dh-net`, `dh-pg-data` + `dh-redis-data`, localhost ports **5436
   (Postgres), 6381 (Redis), and 8007 (API)**, and paths `/var/data/dh/` +
   `/var/backups/dh/`. Never edit MOC, Desk OS, or landing files, Compose projects,
   ports, networks, volumes, routes, or recovery state.

2. **DNS and RDAP do not prove registrability.** They are lifecycle/research
   signals only. Ready requires a non-stale authoritative registrar check and a
   current quote classified `normal`. Unknown, conflicting, premium, auction,
   aftermarket, or unavailable results cannot pass.

3. **Automatic output is research only.** No marketplace source may contain an
   authenticated write/bid/buy/backorder/list method. `research` still carries
   mandatory missing evidence. `/api/pipeline/status` must report automated
   purchase disabled and human approval required.

4. **Source evidence is validated and attributable.** Bulk downloads are cached,
   size/schema/host validated, atomically replaced, and recorded in `source_terms`
   plus `discovery_runs`. NameBio data displayed externally requires attribution.
   Never reinterpret a failed source as zero risk or fabricate a metric.

5. **Name and Authority are independent.** Name qualification excludes backlinks
   and OpenPageRank. Authority provider metrics are prefilters until actual
   independent referring pages are fetched and validated. Neither lane can
   compensate for a failed gate in the other.

6. **GitHub discovery is retired.** Historical code/evidence stays for audit, but
   no GitHub miner or classifier worker may be re-enabled in active discovery.

## Data model — high-level

Legacy tables and XD v1 records are defined in `dh/db/models.py`. The Alembic
chain starts at `20260514_0001_initial_schema.py`; the XD foundation is
`20260821_0006_xd_v1_foundations.py`. Major XD groups include:

- **Core:** `sources`, `candidates`, `source_mentions`, `scoring_weights`, `source_terms` (per-source legal/ToS memory, pre-seeded with 6 rows)
- **Evidence trail (append-only):** `rdap_snapshots`, `availability_checks`, `http_observations`, `wayback_snapshots`, `classification_runs`
- **Independent evaluation:** `lane_assessments`, `gate_results`, and
  `candidate_dossiers`.
- **Content evidence:** `crawl_seeds`, `crawl_runs`, `source_pages`, and detailed
  `link_observations`.
- **Operations:** versioned configs, typed jobs, worker heartbeats, provider
  usage, append-only events/global receipts, device credentials, reviews, and
  portfolio outcomes.

Key invariants in the schema:
- `source_mentions UNIQUE(source_url_hash, cited_url_hash)` — bulk inserts use `ON CONFLICT DO NOTHING` for idempotency. Both hashes are `LargeBinary(32)` = SHA-256 raw bytes.
- `availability_checks.cost_micros BIGINT` (microUSD, not cents — many API calls are below 1¢)
- `availability_checks.is_authoritative BOOLEAN` distinguishes RDAP/WhoisJSON from DNS hints
- `candidates.composite_score` is computed by `dh-worker-scoring`, never by the spike — keeps scoring evolution decoupled from ingestion
- `classification_runs.cache_key` = `sha256(domain ‖ prompt_version ‖ model ‖ classifier_version ‖ sorted(snapshot_ids))` — cache invalidates on any change

## Topology

Container topology (in `compose.yml`):

```
default           : dh-pg, dh-redis, dh-api, vulture,
                    dh-worker-{inventory,rdap,wayback,scoring,operator}
hand-registration : + dh-worker-registrar
```

Each worker owns its own bounded polling loop and Python entry point at
`dh.workers.<name>:main`. Postgres is the source of truth. There is no central
scheduler and no direct worker-to-worker HTTP.

## Gotchas

- **`docker compose run dh-api ...` triggers an autoheal kill-loop.** The compose service has `labels: autoheal: "true"` + a `/health` HTTP healthcheck. A one-shot spike container has no HTTP server → autoheal kills it every ~30 sec. **Use raw `docker run` for spike-style invocations:**
  ```
  docker run -d --name dh-spike-a2 --network domain-hunter_dh-net \
    -v /home/pronav/docker/domain-hunter/docs/spikes:/app/docs/spikes \
    --env-file /home/pronav/docker/domain-hunter/.env \
    domain-hunter-dh-api uv run dh spike a2 --no-dry-run ...
  ```

- **`docker run --env-file` does NOT strip inline comments.** `DH_ENV=dev   # comment` blows up Pydantic. Put comments on the line ABOVE the key. Compose handles comments fine; raw `docker run` does not.

- **gh CLI active account keeps flipping back to `techqubit-pranav`** (no write access to `PranavSlathia/XD`). Always `gh auth switch -u PranavSlathia` immediately before `gh api` / `gh workflow run` / `git push`. The osxkeychain helper caches the wrong token.

- **GitHub Actions runner self-update needs a service restart.** After the first run the runner downloads a new version mid-flight but doesn't restart its listener. Run `ssh pronav@100.103.66.92 'sudo systemctl restart actions.runner.PranavSlathia-XD.dh-dell'` if the runner appears stuck after self-update.

- **Test concurrency.** Test markers in `pyproject.toml`: default selection skips `@pytest.mark.integration` (testcontainers-Postgres). CI runs both. Use `uv run pytest -m integration` locally if you have Docker.

## Memory

`docs/XD-PRD.md`, migrations, and versioned database records are the durable
decision history. Do not rely on private assistant memory as an operational
source of truth.
