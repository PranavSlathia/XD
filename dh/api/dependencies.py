from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from dh.db.engine import session_scope


async def v1_session() -> AsyncGenerator[AsyncSession, None]:
    async with session_scope() as session:
        yield session
