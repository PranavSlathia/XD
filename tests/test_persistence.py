"""Tests for the spike persistence module.

Uses testcontainers to spin up a real Postgres+pgvector for each session,
then applies Alembic migrations and exercises `persist_spike_run` end-to-end.

Skipped automatically if Docker isn't available locally.
"""
from __future__ import annotations

import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    not shutil.which("docker"),
    reason="docker not available; integration tests skipped",
)


@pytest.fixture(scope="session")
def postgres_url() -> AsyncIterator[str]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(
        "pgvector/pgvector:pg16",
        username="dh",
        password="dh-test",
        dbname="dh",
        driver=None,
    ) as pg:
        sync_url = pg.get_connection_url()
        # Convert psycopg2:// to asyncpg://
        async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        if "+asyncpg" not in async_url:
            async_url = async_url.replace("postgresql://", "postgresql+asyncpg://")
        yield async_url


@pytest.fixture(scope="session")
async def migrated_engine(postgres_url: str) -> AsyncIterator[object]:
    engine = create_async_engine(postgres_url)
    # Apply Alembic migrations via the public command API.
    from alembic import command
    from alembic.config import Config

    sync_url = postgres_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    project_root = Path(__file__).parent.parent
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(cfg, "head")
    yield engine
    await engine.dispose()


@pytest.fixture
async def _patched_engine(migrated_engine: object, postgres_url: str) -> AsyncIterator[None]:
    # Force dh.db.engine to use our test engine instead of building from settings.
    with patch.dict(os.environ, {"DH_DB_PASSWORD": "dh-test"}):
        from dh.db import engine as engine_mod

        engine_mod._engine = migrated_engine  # type: ignore[assignment]
        engine_mod._sessionmaker = None
        yield
        engine_mod._engine = None  # type: ignore[assignment]
        engine_mod._sessionmaker = None


@pytest.mark.integration
async def test_persist_smoke(_patched_engine: None) -> None:
    """End-to-end: tiny synthetic spike payload writes cleanly to all 7 tables."""
    from dh.db.engine import session_scope
    from dh.db.models import (
        AvailabilityCheck,
        Candidate,
        HttpObservation,
        Source,
        SourceMention,
    )
    from dh.persistence.spike import persist_spike_run
    from dh.sources.github.repos import ExtractedUrl, Repo
    from dh.sources.openpagerank.client import OPRResult
    from dh.sources.rdap.client import AvailabilityResult
    from dh.spikes.a2 import CandidateRollup

    repo = Repo(owner="acme", name="docs", stars=10_000)
    eu = ExtractedUrl(
        repo=repo,
        file_path="README.md",
        url="https://example.com/dead-link",
        context_type="editorial",
        surrounding="See [the docs](https://example.com/dead-link) for details.",
    )
    rollup = CandidateRollup(domain="example.com", mentions=[eu])
    rollups: dict[str, CandidateRollup] = {"example.com": rollup}

    avail = AvailabilityResult(
        domain="example.com",
        status="available",
        confidence="authoritative",
        source="rdap",
        api_cost_micros=0,
        raw_response={"rdap_server": "https://rdap.example/", "http_status": 404},
    )

    counts = await persist_spike_run(
        rollups=rollups,
        nxdomain_set={"example.com"},
        opr_map={"example.com": OPRResult(domain="example.com", found=False)},
        top_candidates=[rollup],
        avail_results=[avail],
        wb_map={},
    )

    assert counts == {
        "sources_seen": 1,
        "candidates_seen": 1,
        "mentions_attempted": 1,
    }

    from sqlalchemy import select

    async with session_scope() as session:
        srcs = (await session.execute(select(Source))).scalars().all()
        cands = (await session.execute(select(Candidate))).scalars().all()
        ments = (await session.execute(select(SourceMention))).scalars().all()
        avs = (await session.execute(select(AvailabilityCheck))).scalars().all()
        https_ = (await session.execute(select(HttpObservation))).scalars().all()
        assert len(srcs) == 1
        assert srcs[0].source_uri == "github:acme/docs"
        assert len(cands) == 1
        assert cands[0].domain == "example.com"
        assert cands[0].current_status == "available"
        assert cands[0].availability_confidence == "authoritative"
        assert len(ments) == 1
        assert ments[0].context_type == "editorial"
        assert len(avs) == 1
        assert avs[0].is_authoritative is True
        assert avs[0].status == "available"
        assert len(https_) == 1
        assert https_[0].ns_signal == "nxdomain"


@pytest.mark.integration
async def test_persist_is_idempotent(_patched_engine: None) -> None:
    """Re-running persist with the same payload doesn't duplicate rows."""
    from sqlalchemy import func, select

    from dh.db.engine import session_scope
    from dh.db.models import Candidate, Source, SourceMention
    from dh.persistence.spike import persist_spike_run
    from dh.sources.github.repos import ExtractedUrl, Repo
    from dh.sources.openpagerank.client import OPRResult
    from dh.sources.rdap.client import AvailabilityResult
    from dh.spikes.a2 import CandidateRollup

    repo = Repo(owner="other", name="repo", stars=5_000)
    eu = ExtractedUrl(
        repo=repo, file_path="README.md",
        url="https://idempotent.example/x", context_type="editorial",
        surrounding="link to https://idempotent.example/x there",
    )
    rollup = CandidateRollup(domain="idempotent.example", mentions=[eu])
    rollups: dict[str, CandidateRollup] = {"idempotent.example": rollup}
    avail = AvailabilityResult(
        domain="idempotent.example", status="registered",
        confidence="authoritative", source="rdap",
    )

    async def _run() -> None:
        await persist_spike_run(
            rollups=rollups,
            nxdomain_set=set(),
            opr_map={},
            top_candidates=[rollup],
            avail_results=[avail],
            wb_map={},
        )

    await _run()
    await _run()  # second run — should be a no-op for sources/candidates/mentions

    async with session_scope() as session:
        n_sources = (
            await session.execute(
                select(func.count(Source.id)).where(Source.source_uri == "github:other/repo")
            )
        ).scalar_one()
        n_cands = (
            await session.execute(
                select(func.count(Candidate.id)).where(
                    Candidate.domain == "idempotent.example"
                )
            )
        ).scalar_one()
        n_ments = (
            await session.execute(
                select(func.count(SourceMention.id)).where(
                    SourceMention.cited_url == "https://idempotent.example/x"
                )
            )
        ).scalar_one()
        assert n_sources == 1
        assert n_cands == 1
        assert n_ments == 1
