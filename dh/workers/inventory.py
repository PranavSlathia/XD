"""Always-on, read-only pending-delete inventory worker.

The worker intersects DropCatch's public five-day pending-delete feed with the
OpenPageRank Top-10-Million reference before making any per-domain requests.
It records acquisition evidence and a deterministic *research* priority.  It
contains no account credentials and no bid, backorder, purchase, or listing
operation.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import signal
import time
from collections import Counter
from collections.abc import Sequence

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dh.config import settings
from dh.db.engine import session_scope
from dh.db.models import (
    Candidate,
    DiscoveryRun,
    MarketplaceListing,
    OpportunityAssessment,
    SourceTerms,
)
from dh.logging import configure_logging, log
from dh.opportunity import MODEL_VERSION, AssessmentInput, assess
from dh.sources.marketplace.dropcatch import (
    DropCatchDetail,
    DropCatchListing,
    fetch_domain_detail,
    fetch_pending_delete_feed,
)
from dh.sources.namebio.retail_stats import (
    MarketEvidence,
    ensure_retail_stats_dataset,
    find_market_evidence,
    load_retail_stats,
)
from dh.sources.openpagerank.top_domains import (
    TopDomainRecord,
    ensure_top_domains_dataset,
    intersect_top_domains,
)

SOURCE = "dropcatch_pending_delete"
MARKETPLACE = "dropcatch"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _allowed_tlds(raw: str) -> tuple[str, ...]:
    parsed = tuple(
        dict.fromkeys(part.strip().lower().lstrip(".") for part in raw.split(",") if part.strip())
    )
    return parsed or ("com",)


async def _start_run() -> int:
    async with session_scope() as session:
        run = DiscoveryRun(source=SOURCE, status="running")
        session.add(run)
        await session.flush()
        return run.id


async def _finish_failed(run_id: int, error: Exception, elapsed: float) -> None:
    async with session_scope() as session:
        run = await session.get(DiscoveryRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.finished_at = _utcnow()
        run.error = f"{type(error).__name__}: {error}"[:4000]
        run.metrics = {"duration_seconds": round(elapsed, 2)}


async def _fetch_details(
    records: Sequence[TopDomainRecord],
    *,
    limit: int,
    concurrency: int = 4,
) -> tuple[dict[str, DropCatchDetail], dict[str, str]]:
    """Fetch bounded public detail evidence without failing the whole run."""
    selected = records[: max(0, limit)]
    if not selected:
        return {}, {}
    semaphore = asyncio.Semaphore(max(1, concurrency))
    details: dict[str, DropCatchDetail] = {}
    errors: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:

        async def _one(record: TopDomainRecord) -> None:
            async with semaphore:
                try:
                    details[record.domain] = await fetch_domain_detail(record.domain, client=client)
                except Exception as exc:
                    errors[record.domain] = f"{type(exc).__name__}: {exc}"[:500]

        await asyncio.gather(*(_one(record) for record in selected))
    return details, errors


def _prioritize_detail_records(
    records: Sequence[TopDomainRecord],
    *,
    market_by_domain: dict[str, MarketEvidence],
    authority_cohort_sizes: dict[str, int],
) -> list[TopDomainRecord]:
    """Put plausible research candidates inside the bounded detail budget.

    The authority reference arrives in rank order, but a high authority rank is
    not the same thing as resale demand.  Prioritize names with independently
    observed keyword demand, then non-anomalous authority evidence, before the
    deterministic provisional score and authority rank.
    """

    def _key(record: TopDomainRecord) -> tuple[bool, bool, float, int, str]:
        market = market_by_domain.get(record.domain)
        market_qualified = bool(
            market and market.sale_count_floor >= settings.opportunity_min_keyword_sales
        )
        cohort_size = authority_cohort_sizes.get(record.domain, 1)
        result = assess(
            AssessmentInput(
                domain=record.domain,
                open_pagerank=record.open_pagerank,
                referring_domains=record.referring_domains,
                authority_rank=record.rank,
                minimum_price_micros=None,
                # The feed itself supplies a verified drop date. Exact time and
                # opening price are added only when public detail succeeds.
                has_deadline=True,
                market_sale_count_floor=(market.sale_count_floor if market else None),
                market_average_price_floor=(market.price_avg_floor if market else None),
                market_terms=(market.terms if market else ()),
                authority_cohort_size=cohort_size,
                min_market_sale_count_floor=settings.opportunity_min_keyword_sales,
                research_threshold=settings.opportunity_research_threshold,
            )
        )
        return (
            not market_qualified,
            cohort_size >= 5,
            -result.overall_score,
            record.rank,
            record.domain,
        )

    return sorted(records, key=_key)


async def _upsert_source_terms(session: AsyncSession) -> None:
    today = dt.date.today()
    rows = (
        SourceTerms(
            kind=SOURCE,
            license="public_download",
            redistribution_allowed=False,
            attribution_required=False,
            rate_limit_notes="Five-day CSV every six hours; public detail capped and rate-limited.",
            robots_policy="Not used; JSON/CSV endpoints only.",
            terms_url="https://www.dropcatch.com/hiw/terms",
            last_verified_at=today,
            notes="Read-only discovery. No account login, bid, backorder, or purchase calls.",
        ),
        SourceTerms(
            kind="openpagerank_top10m",
            license="published_dataset",
            redistribution_allowed=False,
            attribution_required=True,
            rate_limit_notes="Cached locally; refresh at most every configured reference interval.",
            robots_policy="Not used; documented dataset download only.",
            terms_url="https://openpagerank.keywordseverywhere.com/terms",
            last_verified_at=today,
            notes="Authority prefilter only; not proof of clean backlinks or resale value.",
        ),
        SourceTerms(
            kind="namebio_retailstats",
            license="free_endpoint",
            redistribution_allowed=True,
            attribution_required=True,
            rate_limit_notes="Complete CSV cached for at least 24 hours; no per-keyword requests.",
            robots_policy="Not used; documented dataset download only.",
            terms_url="https://api.namebio.com/docs/",
            last_verified_at=today,
            notes="Aggregated retail keyword statistics. Attribution: NameBio.com.",
        ),
    )
    for desired in rows:
        existing = await session.get(SourceTerms, desired.kind)
        if existing is None:
            session.add(desired)
            continue
        existing.license = desired.license
        existing.redistribution_allowed = desired.redistribution_allowed
        existing.attribution_required = desired.attribution_required
        existing.rate_limit_notes = desired.rate_limit_notes
        existing.robots_policy = desired.robots_policy
        existing.terms_url = desired.terms_url
        existing.last_verified_at = desired.last_verified_at
        existing.notes = desired.notes


async def _persist_matches(
    session: AsyncSession,
    *,
    records: Sequence[TopDomainRecord],
    feed_by_domain: dict[str, DropCatchListing],
    details: dict[str, DropCatchDetail],
    market_by_domain: dict[str, MarketEvidence],
    authority_cohort_sizes: dict[str, int],
    observed_at: dt.datetime,
) -> int:
    if not records:
        return 0

    domains = [record.domain for record in records]
    existing_candidates = (
        (await session.execute(select(Candidate).where(Candidate.domain.in_(domains))))
        .scalars()
        .all()
    )
    candidates = {candidate.domain: candidate for candidate in existing_candidates}

    for record in records:
        candidate = candidates.get(record.domain)
        if candidate is None:
            candidate = Candidate(domain=record.domain, first_observed=observed_at)
            session.add(candidate)
            candidates[record.domain] = candidate
        candidate.last_observed = observed_at
        candidate.current_status = "pending_delete"
        candidate.availability_confidence = "probable"
        candidate.open_pagerank = record.open_pagerank
        candidate.referring_domains = record.referring_domains
        candidate.authority_rank = record.rank
        candidate.authority_source = "openpagerank_top10m"
        candidate.authority_observed_at = observed_at
        candidate.score_version = None
    await session.flush()

    external_keys = [feed_by_domain[record.domain].external_key for record in records]
    existing_listings = (
        (
            await session.execute(
                select(MarketplaceListing).where(
                    MarketplaceListing.marketplace == MARKETPLACE,
                    MarketplaceListing.external_key.in_(external_keys),
                )
            )
        )
        .scalars()
        .all()
    )
    listings = {listing.external_key: listing for listing in existing_listings}

    candidate_ids = [candidates[record.domain].id for record in records]
    existing_assessments = (
        (
            await session.execute(
                select(OpportunityAssessment).where(
                    OpportunityAssessment.candidate_id.in_(candidate_ids),
                    OpportunityAssessment.model_version == MODEL_VERSION,
                )
            )
        )
        .scalars()
        .all()
    )
    assessments = {assessment.candidate_id: assessment for assessment in existing_assessments}

    for record in records:
        candidate = candidates[record.domain]
        feed = feed_by_domain[record.domain]
        detail = details.get(record.domain)
        market = market_by_domain.get(record.domain)
        listing = listings.get(feed.external_key)
        if listing is None:
            listing = MarketplaceListing(
                candidate_id=candidate.id,
                marketplace=MARKETPLACE,
                external_key=feed.external_key,
                acquisition_type="backorder",
                listing_status="active",
                first_seen=observed_at,
            )
            session.add(listing)
        listing.candidate_id = candidate.id
        listing.listing_status = "active"
        listing.drop_date = feed.drop_date
        listing.closes_at = detail.closes_at if detail else None
        listing.minimum_price_micros = detail.minimum_price_micros if detail else None
        listing.current_price_micros = detail.current_price_micros if detail else None
        listing.currency = "USD"
        listing.listing_url = feed.listing_url
        listing.last_seen = observed_at
        listing.raw_response = (
            {
                **detail.raw_response,
                "external_id": detail.external_id,
                "bid_count": detail.bid_count,
            }
            if detail
            else {"feed_record_type": feed.record_type}
        )

        result = assess(
            AssessmentInput(
                domain=record.domain,
                open_pagerank=record.open_pagerank,
                referring_domains=record.referring_domains,
                authority_rank=record.rank,
                minimum_price_micros=(detail.minimum_price_micros if detail else None),
                # DropCatch's signed feed supplies the date even when the
                # optional detail request does not return an exact timestamp.
                has_deadline=bool(feed.drop_date),
                market_sale_count_floor=(market.sale_count_floor if market else None),
                market_average_price_floor=(market.price_avg_floor if market else None),
                market_terms=(market.terms if market else ()),
                authority_cohort_size=authority_cohort_sizes.get(record.domain, 1),
                min_market_sale_count_floor=settings.opportunity_min_keyword_sales,
                research_threshold=settings.opportunity_research_threshold,
            )
        )
        assessment = assessments.get(candidate.id)
        if assessment is None:
            assessment = OpportunityAssessment(
                candidate_id=candidate.id,
                model_version=MODEL_VERSION,
                authority_score=result.authority_score,
                resale_score=result.resale_score,
                risk_score=result.risk_score,
                confidence_score=result.confidence_score,
                overall_score=result.overall_score,
                verdict=result.verdict,
            )
            session.add(assessment)
        assessment.computed_at = observed_at
        assessment.authority_score = result.authority_score
        assessment.resale_score = result.resale_score
        assessment.risk_score = result.risk_score
        assessment.confidence_score = result.confidence_score
        assessment.overall_score = result.overall_score
        assessment.verdict = result.verdict
        assessment.reasons = list(result.reasons)
        assessment.rejection_reasons = list(result.rejection_reasons)
        assessment.missing_evidence = list(result.missing_evidence)
        assessment.signals = {
            **result.signals,
            "namebio_placements": list(market.placements) if market else None,
        }

    await session.execute(
        update(MarketplaceListing)
        .where(
            MarketplaceListing.marketplace == MARKETPLACE,
            MarketplaceListing.listing_status == "active",
            MarketplaceListing.drop_date < observed_at.date(),
            MarketplaceListing.last_seen < observed_at,
        )
        .values(listing_status="expired")
    )
    return len(records)


async def run_once(*, detail_concurrency: int = 4) -> int:
    """Run one complete discovery cycle and return persisted match count."""
    started = time.monotonic()
    run_id = await _start_run()
    observed_at = _utcnow()
    try:
        feed = await fetch_pending_delete_feed(allowed_tlds=_allowed_tlds(settings.inventory_tlds))
        dataset = await ensure_top_domains_dataset(
            settings.inventory_data_dir,
            refresh_after_days=settings.inventory_reference_refresh_days,
        )
        feed_by_domain = {listing.domain: listing for listing in feed.listings}
        records = await asyncio.to_thread(
            intersect_top_domains,
            dataset.path,
            feed_by_domain.keys(),
            min_open_pagerank=settings.inventory_min_opr,
            min_referring_domains=settings.inventory_min_referring_domains,
            limit=settings.inventory_max_candidates,
        )
        market_by_domain: dict[str, MarketEvidence] = {}
        market_error: str | None = None
        market_version: str | None = None
        market_refreshed = False
        try:
            market_dataset = await ensure_retail_stats_dataset(
                settings.inventory_data_dir,
                refresh_after_hours=settings.namebio_retail_stats_refresh_hours,
            )
            retail_stats = await asyncio.to_thread(load_retail_stats, market_dataset.path)
            for record in records:
                evidence = find_market_evidence(record.domain, retail_stats)
                if evidence is not None:
                    market_by_domain[record.domain] = evidence
            market_version = market_dataset.source_version
            market_refreshed = market_dataset.refreshed
        except Exception as exc:
            market_error = f"{type(exc).__name__}: {exc}"[:500]
            log.warning("worker.inventory.namebio.unavailable", error=market_error)
        exact_authority_cohorts = Counter(
            (round(record.open_pagerank, 2), record.referring_domains) for record in records
        )
        bucket_authority_cohorts = Counter(
            (round(record.open_pagerank, 1), round(record.referring_domains, -2))
            for record in records
            if record.open_pagerank >= 5.0
        )
        authority_cohort_sizes = {
            record.domain: max(
                exact_authority_cohorts[(round(record.open_pagerank, 2), record.referring_domains)],
                (
                    bucket_authority_cohorts[
                        (round(record.open_pagerank, 1), round(record.referring_domains, -2))
                    ]
                    if record.open_pagerank >= 5.0
                    else 1
                ),
            )
            for record in records
        }
        prioritized_records = _prioritize_detail_records(
            records,
            market_by_domain=market_by_domain,
            authority_cohort_sizes=authority_cohort_sizes,
        )
        details, detail_errors = await _fetch_details(
            prioritized_records,
            limit=settings.inventory_detail_limit,
            concurrency=detail_concurrency,
        )

        async with session_scope() as session:
            await _upsert_source_terms(session)
            persisted = await _persist_matches(
                session,
                records=records,
                feed_by_domain=feed_by_domain,
                details=details,
                market_by_domain=market_by_domain,
                authority_cohort_sizes=authority_cohort_sizes,
                observed_at=observed_at,
            )
            run = await session.get(DiscoveryRun, run_id)
            if run is None:
                raise RuntimeError(f"discovery run {run_id} disappeared")
            run.status = "partial" if detail_errors or market_error else "success"
            run.finished_at = _utcnow()
            run.source_version = feed.source_version[:128]
            run.fetched_count = feed.fetched_count
            run.prefiltered_count = len(feed.listings)
            run.matched_count = len(records)
            run.persisted_count = persisted
            run.metrics = {
                "authority_reference_version": dataset.source_version,
                "authority_reference_refreshed": dataset.refreshed,
                "market_reference_version": market_version,
                "market_reference_refreshed": market_refreshed,
                "market_matches": len(market_by_domain),
                "market_error": market_error,
                "authority_anomaly_candidates": sum(
                    size >= 5 for size in authority_cohort_sizes.values()
                ),
                "detail_priority_market_qualified": sum(
                    1
                    for record in prioritized_records[: settings.inventory_detail_limit]
                    if (
                        (market := market_by_domain.get(record.domain)) is not None
                        and market.sale_count_floor >= settings.opportunity_min_keyword_sales
                    )
                ),
                "detail_attempted": min(len(records), settings.inventory_detail_limit),
                "detail_succeeded": len(details),
                "detail_failed": len(detail_errors),
                "detail_error_domains": sorted(detail_errors)[:20],
                "duration_seconds": round(time.monotonic() - started, 2),
            }
        log.info(
            "worker.inventory.run.done",
            run_id=run_id,
            fetched=feed.fetched_count,
            prefiltered=len(feed.listings),
            matched=len(records),
            persisted=persisted,
            detail_failed=len(detail_errors),
        )
        return persisted
    except Exception as exc:
        await _finish_failed(run_id, exc, time.monotonic() - started)
        raise


async def _run(shutdown: asyncio.Event, interval_seconds: float) -> None:
    while not shutdown.is_set():
        try:
            await run_once()
        except Exception as exc:
            log.error("worker.inventory.run.error", error=str(exc))
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown: asyncio.Event) -> None:
    def _handler() -> None:
        log.info("worker.inventory.signal.received")
        shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handler)
        except (NotImplementedError, RuntimeError):
            pass


async def _amain() -> None:
    shutdown = asyncio.Event()
    _install_signal_handlers(asyncio.get_running_loop(), shutdown)
    interval = max(1.0, float(settings.inventory_interval_hours)) * 3600.0
    log.info(
        "worker.inventory.start",
        interval_hours=settings.inventory_interval_hours,
        tlds=_allowed_tlds(settings.inventory_tlds),
        authority_floor=settings.inventory_min_opr,
    )
    await _run(shutdown, interval)
    log.info("worker.inventory.exit")


def main() -> None:
    configure_logging()
    from dh.observability import setup_sentry, setup_tracing

    setup_sentry(service="worker-inventory")
    setup_tracing(service="inventory")
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
