# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Domain Hunter — a self-hosted, always-on acquisition-research pipeline. The
default path intersects public pending-delete inventory with authority and
retail-demand references, confirms lifecycle/history evidence, and surfaces a
small human-research queue. It never bids, buys, backorders, lists, contacts, or
spends. Personal-use, localhost/Tailscale-only. Repo: `PranavSlathia/XD`
(deployed at `~/docker/domain-hunter/` on Dell `100.103.66.92`).

Read these before any non-trivial change:
- `docs/ALWAYS_ON_PIPELINE.md` — current product, evidence, safety, and operations contract
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
uv run dh spike a2 --no-dry-run --n-repos 200 --star-floor 500 --pushed-before 2022-01-01
uv run dh db check
uv run dh score normalize-demo

# Run a single test
uv run pytest tests/test_github_context.py::test_code_block_classified_as_operational -v

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

2. **DNS NXDOMAIN is NOT authoritative availability.** `dns_is_nxdomain()` in `dh/sources/rdap/client.py` is a *hint* — it tells us a candidate is worth a paid availability check. Only RDAP / WhoisJSON / WhoisFreaks may set `availability_confidence = 'authoritative'`. Registered domains can have no DNS records; never regress this.

3. **Automatic output is research only.** No marketplace source may contain an
   authenticated write/bid/buy/backorder/list method. `research` still carries
   mandatory missing evidence. `/api/pipeline/status` must report automated
   purchase disabled and human approval required.

4. **Source evidence is validated and attributable.** Bulk downloads are cached,
   size/schema/host validated, atomically replaced, and recorded in `source_terms`
   plus `discovery_runs`. NameBio data displayed externally requires attribution.
   Never reinterpret a failed source as zero risk or fabricate a metric.

5. **Authority is not resale value.** The default funnel is pending-delete
   inventory → authority prefilter → conservative keyword-demand evidence →
   anomaly/risk gates → acquisition detail → RDAP/Wayback → human review. Raw OPR
   rank alone must not decide the detail-request budget or research verdict.

6. **The experimental A2 path/context classifier remains a safety boundary.** If
   the `experimental` profile is enabled, `dh/sources/github/context.py` must keep
   rejecting operational/package/workflow/security URLs. Stub classifier output
   is never persisted as evidence.

## Data model — high-level

The 11 PRD §12 tables are defined in `dh/db/models.py` and applied via the Alembic baseline `alembic/versions/20260514_0001_initial_schema.py`. Three table groups:

- **Core:** `sources`, `candidates`, `source_mentions`, `scoring_weights`, `source_terms` (per-source legal/ToS memory, pre-seeded with 6 rows)
- **Evidence trail (append-only):** `rdap_snapshots`, `availability_checks`, `http_observations`, `wayback_snapshots`, `classification_runs`
- **Decisions:** `outcomes` (operator marks bought/passed/watching/needs_manual_review/lost_to_other; pass_reason enum)

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
                    dh-worker-{inventory,rdap,wayback,scoring}
experimental      : + dh-worker-{a2,classifier}
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

Project memory lives at `~/.claude/projects/-Users-pronav/memory/project_domain_hunter.md`. Read it at the start of any new session for the latest spike results, gotchas, and decision history.
