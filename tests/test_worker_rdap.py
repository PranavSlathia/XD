"""Integration tests for the RDAP enrichment worker.

Reuses the testcontainer Postgres fixture pattern from test_persistence.py.
"""
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
async def test_rdap_worker_writes_evidence(_patched_engine: None) -> None:
    from dh.db.engine import session_scope
    from dh.db.models import AvailabilityCheck, Candidate, RdapSnapshot
    from dh.sources.rdap.client import AvailabilityResult
    from dh.workers import rdap as worker

    # Seed a candidate.
    async with session_scope() as session:
        c = Candidate(domain="rdap-worker-test.example")
        session.add(c)

    fake = AvailabilityResult(
        domain="rdap-worker-test.example",
        status="available",
        confidence="authoritative",
        source="rdap",
        raw_response={"rdap_server": "https://example/", "http_status": 404},
    )

    async def _fake_check(domain: str) -> AvailabilityResult:
        return fake.model_copy(update={"domain": domain})

    with patch("dh.workers.rdap.check_availability", AsyncMock(side_effect=_fake_check)):
        n = await worker.run_batch(batch_size=10, concurrency=1)
    assert n == 1

    from sqlalchemy import select

    async with session_scope() as session:
        avs = (await session.execute(select(AvailabilityCheck))).scalars().all()
        snaps = (await session.execute(select(RdapSnapshot))).scalars().all()
        cands = (
            await session.execute(
                select(Candidate).where(Candidate.domain == "rdap-worker-test.example")
            )
        ).scalars().all()
    assert len(avs) == 1
    assert avs[0].status == "available"
    assert avs[0].is_authoritative is True
    assert len(snaps) == 1
    assert cands[0].current_status == "available"
    assert cands[0].availability_confidence == "authoritative"

    # Running again should not re-enrich the same candidate (fresh evidence row).
    with patch("dh.workers.rdap.check_availability", AsyncMock(side_effect=_fake_check)):
        n2 = await worker.run_batch(batch_size=10, concurrency=1)
    assert n2 == 0
