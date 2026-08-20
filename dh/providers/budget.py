from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from dh.db.models import ProviderUsage


class ProviderBudgetExhaustedError(RuntimeError):
    pass


def _month_start() -> dt.datetime:
    now = dt.datetime.now(dt.UTC)
    return dt.datetime(now.year, now.month, 1, tzinfo=dt.UTC)


async def reserve_provider_budget(
    session: AsyncSession,
    *,
    provider: str,
    operation: str,
    request_id: str,
    reserve_micros: int,
    monthly_cap_micros: int,
    candidate_id: int | None = None,
) -> ProviderUsage:
    # Serialize reservations per provider. This prevents two workers from both
    # observing spare budget and crossing the hard cap together.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:provider))"), {"provider": provider}
    )
    used = (
        await session.execute(
            select(func.coalesce(func.sum(ProviderUsage.cost_micros), 0)).where(
                ProviderUsage.provider == provider,
                ProviderUsage.occurred_at >= _month_start(),
            )
        )
    ).scalar_one()
    if int(used) + reserve_micros > monthly_cap_micros:
        raise ProviderBudgetExhaustedError(
            f"{provider} monthly enrichment budget exhausted; evidence remains pending"
        )
    row = ProviderUsage(
        provider=provider,
        operation=f"reserve:{operation}",
        cost_micros=reserve_micros,
        request_id=request_id,
        candidate_id=candidate_id,
    )
    session.add(row)
    await session.flush()
    return row


async def settle_provider_budget(
    session: AsyncSession,
    *,
    reservation_id: int,
    operation: str,
    actual_cost_micros: int,
) -> None:
    await session.execute(
        update(ProviderUsage)
        .where(ProviderUsage.id == reservation_id)
        .values(operation=operation, cost_micros=max(0, actual_cost_micros))
    )
