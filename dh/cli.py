"""`dh` CLI - Typer-based admin/ops entry point.

Subcommands:
    dh spike a2             - Phase 0.5 A2 yield spike
    dh db check             - validate config + connectivity (read-only)
    dh score normalize-demo - print sample normalization outputs
"""
from __future__ import annotations

import asyncio
import json

import typer
from sqlalchemy import text

from dh.config import settings
from dh.db.engine import get_engine, session_scope
from dh.logging import configure_logging
from dh.score import normalize
from dh.security.device_auth import create_pairing_code

configure_logging()

app = typer.Typer(no_args_is_help=True, add_completion=False)
db_app = typer.Typer(help="Database helpers (no destructive ops).")
score_app = typer.Typer(help="Scoring + normalization utilities.")
device_app = typer.Typer(help="Pair and revoke private XD devices.")

app.add_typer(db_app, name="db")
app.add_typer(score_app, name="score")
app.add_typer(device_app, name="device")


@db_app.command("check")
def db_check_cmd() -> None:
    """Print the resolved DB URL (masked) and try a SELECT 1. Read-only."""
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
            typer.echo(f"SELECT 1 -> {row}")
        await engine.dispose()

    try:
        asyncio.run(_ping())
    except Exception as e:
        typer.echo(f"connection error: {e}", err=True)
        raise typer.Exit(code=1) from None


@score_app.command("normalize-demo")
def score_normalize_demo() -> None:
    """Print sample normalization outputs (sanity check on PRD §4.5)."""
    samples = {
        "max_source_authority(stars=12)": normalize.normalize_max_source_authority(12),
        "max_source_authority(stars=5_000)": normalize.normalize_max_source_authority(5_000),
        "max_source_authority(stars=50_000)": normalize.normalize_max_source_authority(50_000),
        "diversity(sources=1)": normalize.normalize_source_diversity(1),
        "diversity(sources=3)": normalize.normalize_source_diversity(3),
        "diversity(sources=10)": normalize.normalize_source_diversity(10),
        "referring_domains(count=10)": normalize.normalize_referring_domains(10),
        "referring_domains(count=100)": normalize.normalize_referring_domains(100),
        "open_pagerank(opr=3.2)": normalize.normalize_open_pagerank(3.2),
        "age(years=5)": normalize.normalize_age(5),
        "age(years=20)": normalize.normalize_age(20),
    }
    typer.echo(json.dumps({k: round(v, 1) for k, v in samples.items()}, indent=2))


@device_app.command("pairing-code")
def device_pairing_code(
    ttl_minutes: int = typer.Option(10, min=1, max=60, help="One-time code lifetime."),
) -> None:
    """Generate a one-time code on the private server for an XD Mac."""

    async def _create() -> str:
        async with session_scope() as session:
            code, _row = await create_pairing_code(session, ttl_minutes=ttl_minutes)
            return code

    typer.echo(asyncio.run(_create()))


@app.callback()
def root() -> None:
    """Domain Hunter ops CLI."""


if __name__ == "__main__":
    app()
