"""Wayback content-history classifier worker.

Polls candidates that have a `wayback_snapshots` row but no recent
`classification_runs` (or a stale one with mismatched cache_key) and runs the
configured ClassifierClient implementation.

Default transport is `stub` — deterministic, free, fine for the dashboard to
have non-empty classification data. Switch DH_CLASSIFIER_TRANSPORT=codex_cli
once `dh.classify.codex` is fully implemented (currently only the
cap-exceeded path returns a real value).
"""
from __future__ import annotations

import asyncio
import signal
from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dh.classify.base import (
    ClassifierClient,
    WaybackClassifierInput,
    WaybackSnapshotRef,
    compute_cache_key,
)
from dh.classify.factory import make_classifier
from dh.config import settings
from dh.db.engine import session_scope
from dh.db.models import ClassificationRun
from dh.logging import configure_logging, log

STALE_AFTER_DAYS = 30


async def _claim_batch(
    session: AsyncSession, *, batch_size: int
) -> list[tuple[int, str, list[str]]]:
    """Return (id, domain, snapshot_ids) for candidates needing classification.

    Snapshot IDs are pulled from cdx_summary JSON (first/last capture timestamps).
    """
    sql = text(
        """
        SELECT c.id, c.domain, w.cdx_summary, w.first_capture, w.last_capture
        FROM candidates c
        JOIN LATERAL (
            SELECT cdx_summary, first_capture, last_capture
            FROM wayback_snapshots
            WHERE candidate_id = c.id
            ORDER BY observed_at DESC
            LIMIT 1
        ) w ON TRUE
        WHERE NOT EXISTS (
            SELECT 1 FROM classification_runs cr
            WHERE cr.candidate_id = c.id
              AND cr.observed_at > now() - (:stale || ' days')::interval
        )
        ORDER BY c.composite_score DESC NULLS LAST
        LIMIT :lim
        """
    )
    res = await session.execute(
        sql, {"stale": STALE_AFTER_DAYS, "lim": batch_size}
    )
    out: list[tuple[int, str, list[str]]] = []
    for row in res.all():
        cid, domain, cdx_summary, fc, lc = row
        snap_ids: list[str] = []
        if cdx_summary:
            for k in ("first_capture_ts", "last_capture_ts"):
                v = cdx_summary.get(k) if isinstance(cdx_summary, dict) else None
                if isinstance(v, str):
                    snap_ids.append(v)
        out.append((cid, domain, snap_ids))
    return out


async def _persist(
    session: AsyncSession,
    *,
    candidate_id: int,
    domain: str,
    snapshot_ids: list[str],
    classifier: ClassifierClient,
    result: object,
) -> None:
    r = cast("dict[str, object]", result.model_dump())  # type: ignore[attr-defined]
    cache_key = compute_cache_key(
        domain=domain,
        prompt_version=str(r["prompt_version"]),
        model_used=str(r["model_used"]),
        classifier_version=str(getattr(classifier, "classifier_version", "0.0.0")),
        snapshot_ids=snapshot_ids,
    )
    session.add(
        ClassificationRun(
            candidate_id=candidate_id,
            prompt_version=str(r["prompt_version"]),
            model_used=str(r["model_used"]),
            classifier_version=str(getattr(classifier, "classifier_version", "0.0.0")),
            snapshot_ids=snapshot_ids or None,
            classification=str(r["classification"]),
            confidence=float(cast("float", r["confidence"])),
            cost_micros=int(cast("int", r["cost_micros"])),
            cache_key=cache_key,
            raw_response=r,
        )
    )


async def run_batch(*, batch_size: int) -> int:
    classifier = make_classifier()
    async with session_scope() as session:
        rows = await _claim_batch(session, batch_size=batch_size)
    if not rows:
        return 0

    processed = 0
    for cid, domain, snap_ids in rows:
        snaps = [
            WaybackSnapshotRef(urlkey=domain, timestamp=ts, original=f"https://{domain}")
            for ts in snap_ids
        ]
        try:
            result = await classifier.classify_wayback_history(
                WaybackClassifierInput(domain=domain, snapshots=snaps)
            )
        except NotImplementedError:
            log.warning("classifier.not_implemented", domain=domain)
            continue
        except Exception as e:  # noqa: BLE001
            log.warning("classifier.error", domain=domain, error=str(e))
            continue
        async with session_scope() as session:
            await _persist(
                session,
                candidate_id=cid,
                domain=domain,
                snapshot_ids=snap_ids,
                classifier=classifier,
                result=result,
            )
        processed += 1
    return processed


async def loop() -> None:
    configure_logging()
    log.info(
        "worker.classifier.start",
        transport=settings.classifier_transport,
        interval_s=60,
    )
    stop = asyncio.Event()
    loop_ = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop_.add_signal_handler(sig, stop.set)
    while not stop.is_set():
        try:
            n = await run_batch(batch_size=20)
            log.info("worker.classifier.tick", processed=n)
        except Exception as e:  # noqa: BLE001
            log.error("worker.classifier.error", error=str(e))
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
    log.info("worker.classifier.shutdown")


def main() -> None:
    asyncio.run(loop())


if __name__ == "__main__":
    main()
