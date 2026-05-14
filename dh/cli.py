"""`dh` CLI — Typer-based admin/ops entry point.

Subcommands:
    dh discord smoke       — manual; posts to DH_DISCORD_WEBHOOK_URL if set
    dh spike a2            — Phase 0.5 A2 yield spike
    dh db check            — validate config + connectivity (no destructive ops)
    dh score normalize-demo — print sample normalization outputs
"""
from __future__ import annotations

import asyncio
import json

import typer

from dh.logging import configure_logging, log

configure_logging()

app = typer.Typer(no_args_is_help=True, add_completion=False)

discord_app = typer.Typer(help="Discord webhook commands.")
spike_app = typer.Typer(help="Phase-0.5 spike harnesses.")
db_app = typer.Typer(help="Database helpers (no destructive ops).")
score_app = typer.Typer(help="Scoring + normalization utilities.")

app.add_typer(discord_app, name="discord")
app.add_typer(spike_app, name="spike")
app.add_typer(db_app, name="db")
app.add_typer(score_app, name="score")


# --------------------------------------------------------------------------- #
# discord
# --------------------------------------------------------------------------- #

@discord_app.command("smoke")
def discord_smoke_cmd() -> None:
    """Send a smoke-test message to Discord. No-op if webhook is not configured."""
    from dh.notifications.discord import (
        DiscordWebhookNotConfigured,
        discord_smoke,
    )

    try:
        asyncio.run(discord_smoke())
        log.info("discord.smoke.sent")
    except DiscordWebhookNotConfigured as e:
        log.warning("discord.smoke.skipped", reason=str(e))
        raise typer.Exit(code=0) from None


# --------------------------------------------------------------------------- #
# spike a2
# --------------------------------------------------------------------------- #

@spike_app.command("a2")
def spike_a2_cmd(
    n_repos: int = typer.Option(1000, help="How many repos to sample."),
    star_floor: int = typer.Option(5000, help="Minimum star count to consider."),
    pushed_before: str = typer.Option(
        "", help="ISO date 'YYYY-MM-DD'. Restrict to repos last pushed before this."
    ),
    extra_query: str = typer.Option(
        "",
        "--query",
        help="Raw GitHub-search qualifier appended to the query, e.g. 'awesome in:name'.",
    ),
    dry_run: bool = typer.Option(
        True,
        help="Skip live external calls (default in scaffold mode).",
    ),
) -> None:
    """Run the Phase 0.5 A2 yield spike."""
    from dh.spikes.a2 import SpikeConfig, run_a2_spike

    cfg = SpikeConfig(
        n_repos=n_repos,
        star_floor=star_floor,
        pushed_before=pushed_before or None,
        extra_query=extra_query or None,
    )
    log.info(
        "spike.a2.start",
        n_repos=n_repos,
        star_floor=star_floor,
        pushed_before=pushed_before or None,
        extra_query=extra_query or None,
        dry_run=dry_run,
    )

    if dry_run:
        typer.echo(
            "dry-run: scaffold mode. No external calls made. "
            "Pass `--no-dry-run` once env + Docker + BQ creds are wired up."
        )
        raise typer.Exit(code=0)

    try:
        asyncio.run(run_a2_spike(cfg))
    except NotImplementedError as e:
        log.error("spike.a2.not_implemented", error=str(e))
        raise typer.Exit(code=1) from None


# --------------------------------------------------------------------------- #
# db check
# --------------------------------------------------------------------------- #

@db_app.command("check")
def db_check_cmd() -> None:
    """Print the resolved DB URL (masked) and try a SELECT 1. Read-only."""
    from sqlalchemy import text

    from dh.config import settings
    from dh.db.engine import get_engine

    masked = (
        f"postgresql+asyncpg://{settings.db_user}:***"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )
    typer.echo(f"DB URL: {masked}")

    async def _ping() -> None:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            row = result.scalar_one()
            typer.echo(f"SELECT 1 → {row}")
        await engine.dispose()

    try:
        asyncio.run(_ping())
    except Exception as e:  # noqa: BLE001
        typer.echo(f"connection error: {e}", err=True)
        raise typer.Exit(code=1) from None


# --------------------------------------------------------------------------- #
# score normalize-demo
# --------------------------------------------------------------------------- #

@score_app.command("normalize-demo")
def score_normalize_demo() -> None:
    """Print sample normalization outputs (sanity check on PRD §4.5)."""
    from dh.score import normalize as N

    samples = {
        "max_source_authority(stars=12)":      N.normalize_max_source_authority(12),
        "max_source_authority(stars=5_000)":   N.normalize_max_source_authority(5_000),
        "max_source_authority(stars=50_000)":  N.normalize_max_source_authority(50_000),
        "diversity(sources=1)":                N.normalize_source_diversity(1),
        "diversity(sources=3)":                N.normalize_source_diversity(3),
        "diversity(sources=10)":               N.normalize_source_diversity(10),
        "referring_domains(count=10)":         N.normalize_referring_domains(10),
        "referring_domains(count=100)":        N.normalize_referring_domains(100),
        "open_pagerank(opr=3.2)":              N.normalize_open_pagerank(3.2),
        "age(years=5)":                        N.normalize_age(5),
        "age(years=20)":                       N.normalize_age(20),
    }
    typer.echo(json.dumps({k: round(v, 1) for k, v in samples.items()}, indent=2))


# --------------------------------------------------------------------------- #
# top-level
# --------------------------------------------------------------------------- #

@app.callback()
def root() -> None:
    """Domain Hunter ops CLI."""


if __name__ == "__main__":
    app()
