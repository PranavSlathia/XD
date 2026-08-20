"""Alembic environment.

Resolves the DB URL from dh.config.Settings, so we don't store secrets in alembic.ini.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from dh.config import settings
from dh.db.models import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _configured_url(*, async_driver: bool) -> str:
    """Honor programmatic Alembic URLs while keeping env settings as default."""
    configured = config.get_main_option("sqlalchemy.url", "").split(";", 1)[0].strip()
    if not configured or configured.startswith("driver://"):
        return settings.db_url_async if async_driver else settings.db_url_sync
    if async_driver:
        return configured.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    return configured.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def run_migrations_offline() -> None:
    context.configure(
        url=_configured_url(async_driver=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _configured_url(async_driver=True)
    connectable = async_engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_migrations_online_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
