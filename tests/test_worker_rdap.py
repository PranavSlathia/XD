"""Integration tests for the RDAP enrichment worker.

Reuses the testcontainer Postgres fixture pattern from test_persistence.py.
"""

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
async def test_rdap_worker_writes_evidence(patched_engine: None) -> None:
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
            (
                await session.execute(
                    select(Candidate).where(Candidate.domain == "rdap-worker-test.example")
                )
            )
            .scalars()
            .all()
        )
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


@pytest.mark.integration
async def test_latest_manual_decision_gates_actionable_work(patched_engine: None) -> None:
    from sqlalchemy import select

    from dh.api.main import _terminal_decision_exists
    from dh.db.engine import session_scope
    from dh.db.models import Candidate, MarketplaceListing, OpportunityAssessment, Outcome
    from dh.opportunity import MODEL_VERSION
    from dh.workers.rdap import _claim_batch

    now = dt.datetime.now(dt.UTC)
    async with session_scope() as session:
        closed = Candidate(domain="manual-closed-test.com")
        open_candidate = Candidate(domain="manual-open-test.com")
        session.add_all((closed, open_candidate))
        await session.flush()
        for candidate in (closed, open_candidate):
            session.add(
                MarketplaceListing(
                    candidate_id=candidate.id,
                    marketplace="test",
                    external_key=f"{candidate.domain}:test",
                    acquisition_type="backorder",
                    listing_status="active",
                    drop_date=now.date() + dt.timedelta(days=1),
                )
            )
            session.add(
                OpportunityAssessment(
                    candidate_id=candidate.id,
                    model_version=MODEL_VERSION,
                    authority_score=50,
                    resale_score=50,
                    risk_score=10,
                    confidence_score=50,
                    overall_score=50,
                    verdict="research",
                )
            )
        session.add(
            Outcome(
                candidate_id=closed.id,
                decided_at=now,
                decision="passed",
                pass_reason="tm_risk",
            )
        )

    async with session_scope() as session:
        due = await _claim_batch(session, batch_size=100)
        actionable = set(
            (
                await session.execute(
                    select(Candidate.domain).where(
                        Candidate.domain.in_((closed.domain, open_candidate.domain)),
                        ~_terminal_decision_exists(Candidate.id),
                    )
                )
            ).scalars()
        )

    assert open_candidate.domain in {domain for _candidate_id, domain in due}
    assert closed.domain not in {domain for _candidate_id, domain in due}
    assert actionable == {open_candidate.domain}

    async with session_scope() as session:
        session.add(
            Outcome(
                candidate_id=closed.id,
                decided_at=now + dt.timedelta(seconds=1),
                decision="watching",
            )
        )
    async with session_scope() as session:
        reopened = set(
            (
                await session.execute(
                    select(Candidate.domain).where(
                        Candidate.domain == closed.domain,
                        ~_terminal_decision_exists(Candidate.id),
                    )
                )
            ).scalars()
        )
    assert reopened == {closed.domain}


@pytest.mark.integration
async def test_terminal_decision_gates_inactive_legacy_candidate(
    patched_engine: None,
) -> None:
    """The terminal-outcome predicate covers both active and legacy branches."""
    from dh.db.engine import session_scope
    from dh.db.models import Candidate, Outcome
    from dh.workers.rdap import _claim_batch

    async with session_scope() as session:
        candidate = Candidate(domain="manual-closed-legacy.example")
        session.add(candidate)
        await session.flush()
        session.add(
            Outcome(
                candidate_id=candidate.id,
                decision="passed",
                pass_reason="other",
            )
        )

    async with session_scope() as session:
        due = await _claim_batch(session, batch_size=100)

    assert candidate.domain not in {domain for _candidate_id, domain in due}
