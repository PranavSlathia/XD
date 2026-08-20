"""Integration test for the Wayback enrichment worker."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    not shutil.which("docker"),
    reason="docker not available; integration tests skipped",
)


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
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


@pytest.fixture
async def migrated_engine(postgres_url: str) -> AsyncIterator[object]:
    engine = create_async_engine(postgres_url)
    from alembic.config import Config

    from alembic import command

    sync_url = postgres_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    project_root = Path(__file__).parent.parent
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", sync_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    yield engine
    await engine.dispose()


@pytest.fixture
async def patched_engine(migrated_engine: object) -> AsyncIterator[None]:
    with patch.dict(os.environ, {"DH_DB_PASSWORD": "dh-test"}):
        from dh.db import engine as engine_mod

        engine_mod._engine = migrated_engine  # type: ignore[assignment]
        engine_mod._sessionmaker = None
        yield
        engine_mod._engine = None  # type: ignore[assignment]
        engine_mod._sessionmaker = None


@pytest.mark.integration
async def test_wayback_worker_writes_snapshot(patched_engine: None) -> None:
    from dh.db.engine import session_scope
    from dh.db.models import (
        Candidate,
        MarketplaceListing,
        OpportunityAssessment,
        WaybackSnapshot,
    )
    from dh.opportunity import MODEL_VERSION
    from dh.sources.wayback.cdx import CdxSummary
    from dh.workers import wayback as worker

    async with session_scope() as session:
        c = Candidate(domain="wb-test.example", open_pagerank=3.0)
        session.add(c)
        await session.flush()
        session.add_all(
            [
                MarketplaceListing(
                    candidate_id=c.id,
                    marketplace="test",
                    external_key="wb-test.example:test",
                    acquisition_type="backorder",
                    listing_status="active",
                    drop_date=dt.date.today() + dt.timedelta(days=1),
                ),
                OpportunityAssessment(
                    candidate_id=c.id,
                    model_version=MODEL_VERSION,
                    authority_score=50,
                    resale_score=50,
                    risk_score=10,
                    confidence_score=50,
                    overall_score=50,
                    verdict="research",
                ),
            ]
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


@pytest.mark.integration
async def test_wayback_failure_writes_no_false_zero_snapshot(
    patched_engine: None,
) -> None:
    from sqlalchemy import select

    from dh.db.engine import session_scope
    from dh.db.models import (
        Candidate,
        MarketplaceListing,
        OpportunityAssessment,
        WaybackSnapshot,
    )
    from dh.opportunity import MODEL_VERSION
    from dh.workers import wayback as worker

    async with session_scope() as session:
        candidate = Candidate(domain="wb-failure-test.example", open_pagerank=3.0)
        session.add(candidate)
        await session.flush()
        candidate_id = candidate.id
        session.add_all(
            [
                MarketplaceListing(
                    candidate_id=candidate_id,
                    marketplace="test",
                    external_key="wb-failure-test.example:test",
                    acquisition_type="backorder",
                    listing_status="active",
                    drop_date=dt.date.today() + dt.timedelta(days=1),
                ),
                OpportunityAssessment(
                    candidate_id=candidate_id,
                    model_version=MODEL_VERSION,
                    authority_score=50,
                    resale_score=50,
                    risk_score=10,
                    confidence_score=50,
                    overall_score=49,
                    verdict="research",
                ),
            ]
        )

    with patch(
        "dh.workers.wayback.fetch_cdx",
        AsyncMock(side_effect=RuntimeError("upstream unavailable")),
    ):
        processed = await worker.run_batch(batch_size=10, top_n=10, concurrency=1)

    async with session_scope() as session:
        snapshots = (
            await session.execute(
                select(WaybackSnapshot).where(WaybackSnapshot.candidate_id == candidate_id)
            )
        ).scalars()

    assert processed == 0
    assert snapshots.first() is None
