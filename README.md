# Domain Hunter

Self-hosted expired-domain discovery + scoring pipeline. Personal use, Tailscale-only.

**Scope:** ingest → enrich → score → daily ranked shortlist. Acquisition + flipping handled separately by the operator.

See `docs/`:
- `PRD.md` — product requirements
- `RESEARCH.md` — methodology research + repo audit
- `TECH_STACK.md` — every locked technical decision
- `IMPLEMENTATION_NOTES.md` — repo + API audit
- `CZDS_APPLICATIONS.md` — zone-file access application template
- `spikes/` — Phase 0.5 yield-spike outputs

## Status

Phase 0 — scaffold only. **Containers NOT started.** No live external calls yet.

Next: `dh spike a2` once Phase 0 is committed and Docker / env / ports on the Dell are confirmed.

## Quick reference

```
# Install (after `uv` is on PATH)
uv sync

# Run CLI
uv run dh --help

# Spike (Phase 0.5)
uv run dh spike a2 --n-repos 500

# Bring up Postgres + Redis (only after .env is filled in)
docker compose --profile foundation up -d dh-pg dh-redis

# Run Alembic baseline
uv run alembic upgrade head

# Discord smoke (manual; only works once DH_DISCORD_WEBHOOK_URL is set)
uv run dh discord smoke
```
