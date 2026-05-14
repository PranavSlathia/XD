# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Domain Hunter — a self-hosted pipeline that ingests external-URL citations from authority graphs (GitHub READMEs, academic papers, patents), filters for dead/available domains, scores them, and surfaces a daily shortlist. Personal-use tool, Tailscale-only. Repo: `PranavSlathia/XD` (deployed at `~/docker/domain-hunter/` on Dell `100.103.66.92`).

Authoritative docs live in `docs/` — read these before any non-trivial change:
- `PRD.md` — product scope (the §12 data model is canonical)
- `TECH_STACK.md` — every locked tech decision
- `RESEARCH.md` — methodology research + repo audit
- `IMPLEMENTATION_NOTES.md` — per-repo + per-API audit notes

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

`.github/workflows/build.yml` runs on a **self-hosted GitHub Actions runner on the Dell** (systemd unit `actions.runner.PranavSlathia-XD.dh-dell`). Every push to `main` rebuilds the `dh-api` Docker image on the Dell and restarts `dh-api` if it's already running.

The runner survives reboots. Workflow is guarded with `if: github.repository == 'PranavSlathia/XD' && github.event_name != 'pull_request'` because the repo is public — fork PRs cannot execute the runner.

## Architecture invariants (do not violate)

1. **MOC isolation is non-negotiable.** Domain Hunter uses `dh-*` container names (`dh-pg`, `dh-redis`, `dh-api`, `dh-worker-*`, `dh-scheduler`), `dh-net` network, `dh-pg-data` + `dh-redis-data` volumes, host ports **5436 (pg) + 6381 (redis)**, paths `/var/data/dh/` + `/var/backups/dh/`. Never edit anything under `~/docker/moc/` on the Dell. Port 6380 belongs to `moc-falkordb`; never use it.

2. **DNS NXDOMAIN is NOT authoritative availability.** `dns_is_nxdomain()` in `dh/sources/rdap/client.py` is a *hint* — it tells us a candidate is worth a paid availability check. Only RDAP / WhoisJSON / WhoisFreaks may set `availability_confidence = 'authoritative'`. Registered domains can have no DNS records; never regress this.

3. **The A2 path/context safety classifier is the safety boundary.** `dh/sources/github/context.py` rejects URLs from `requirements.txt`, `package.json`, `Dockerfile`, `.github/workflows/`, `SECURITY.md`, fenced code blocks, API endpoints, asset hosts, etc. Registering an operational URL would create a supply-chain-attack surface. 36 parametrised tests in `tests/test_github_context.py` guard the rule set — extend them when adding categories.

4. **Classifier transport is behind `ClassifierClient` ABC.** Workers and the spike never import a concrete classifier; they call `make_classifier()` which reads `DH_CLASSIFIER_TRANSPORT`. Codex CLI is the locked transport per `TECH_STACK.md`; Anthropic / OpenAI / Stub implementations are slots. Keep the interface stable.

5. **Deadness-first ranking is canonical.** The original ranking-by-`source_authority × mentions` is structurally broken — it surfaces github.com / npmjs.com / arxiv.org because they're the most-mentioned-anywhere, which means they're the most-alive. Correct order: (1) DNS-sweep all candidates, (2) keep NXDOMAIN survivors, (3) Open PageRank lookup, (4) rank survivors by OPR, then max source authority, then diversity. See `dh/spikes/a2.py:run_a2_spike` for the canonical pipeline.

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

Container topology (in `compose.yml`, profiled):
```
foundation : dh-pg, dh-redis                                (Phase 0)
api        : foundation + dh-api                            (Phase 1)
workers    : foundation + dh-scheduler + dh-worker-{a2,rdap,wayback,classifier,scoring}
all        : everything
```

Worker pattern: each worker is its own container with its own Python entry point at `dh.workers.<name>:main`. Workers communicate via Postgres as source of truth + Redis pub/sub for low-latency dashboard notifications. No direct worker-to-worker HTTP.

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
