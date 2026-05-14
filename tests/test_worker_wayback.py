"""Integration test for the Wayback enrichment worker."""
from __future__ import annotations

import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
        async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
        if "+asyncpg" not in async_url:
            async_url = async_url.replace("postgresql://", "postgresql+asyncpg://")
        yield async_url


@pytest.fixture(scope="session")
async def migrated_engine(postgres_url: str) -> AsyncIterator[object]:
    engine = create_async_engine(postgres_url)
    from alembic.config import Config

    from alembic import command

    sync_url = postgres_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    project_root = Path(__file__).parent.parent
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(cfg, "head")
    yield engine
    await engine.dispose()


@pytest.fixture
async def _patched_engine(migrated_engine: object) -> AsyncIterator[None]:
    with patch.dict(os.environ, {"DH_DB_PASSWORD": "dh-test"}):
        from dh.db import engine as engine_mod

        engine_mod._engine = migrated_engine  # type: ignore[assignment]
        engine_mod._sessionmaker = None
        yield
        engine_mod._engine = None  # type: ignore[assignment]
        engine_mod._sessionmaker = None


@pytest.mark.integration
async def test_wayback_worker_writes_snapshot(_patched_engine: None) -> None:
    from dh.db.engine import session_scope
    from dh.db.models import Candidate, Source, SourceMention, WaybackSnapshot
    from dh.sources.wayback.cdx import CdxSummary
    from dh.workers import wayback as worker

    async with session_scope() as session:
        c = Candidate(domain="wb-test.example")
        s = Source(kind="github_readme", source_uri="github:a/b", authority=10000)
        session.add_all([c, s])
        await session.flush()
        session.add(
            SourceMention(
                candidate_id=c.id,
                source_id=s.id,
                source_url="https://github.com/a/b",
                cited_url="https://wb-test.example/",
            )
        )

    async def _fake(domain: str) -> CdxSummary:
        return CdxSummary(
            domain=domain,
            first_capture="20100101000000",
            last_capture="20200101000000",
            capture_count=5,
        )

    with patch("dh.workers.wayback.fetch_cdx", AsyncMock(side_effect=_fake)):
        n = await worker.run_batch(batch_size=10, top_n=10, concurrency=1)
    assert n == 1

    from sqlalchemy import select

    async with session_scope() as session:
        snaps = (await session.execute(select(WaybackSnapshot))).scalars().all()
    assert len(snaps) == 1
    assert snaps[0].capture_count == 5
