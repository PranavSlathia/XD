from __future__ import annotations

import datetime as dt
import heapq
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dh.db.models import (
    Candidate,
    CandidateEvent,
    GateResult,
    LaneAssessment,
    MarketplaceListing,
)
from dh.engine.configuration import get_active_config
from dh.lanes.authority import AuthorityScreenInput, screen_authority
from dh.lanes.gates import LANE_GATES, SHARED_GATES
from dh.lanes.name import NameScreenResult, screen_name
from dh.lanes.types import GateState, Lane
from dh.sources.marketplace.dropcatch import DropCatchListing
from dh.sources.openpagerank.top_domains import TopDomainRecord


@dataclass(frozen=True, slots=True)
class NameInventoryCandidate:
    listing: DropCatchListing
    assessment: NameScreenResult


def screen_name_inventory(
    listings: tuple[DropCatchListing, ...],
    *,
    minimum_score: float,
    limit: int,
) -> tuple[NameInventoryCandidate, ...]:
    """Evaluate every feed name, retaining only the bounded best screen hits."""

    heap: list[tuple[float, int, str, DropCatchListing, NameScreenResult]] = []
    for listing in listings:
        result = screen_name(listing.domain, minimum_score=minimum_score)
        if not result.screen_passed:
            continue
        label = listing.domain.rsplit(".", 1)[0]
        item = (result.score, -len(label), listing.domain, listing, result)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item[:3] > heap[0][:3]:
            heapq.heapreplace(heap, item)
    ranked = sorted(heap, key=lambda item: (-item[0], -item[1], item[2]))
    return tuple(NameInventoryCandidate(listing=item[3], assessment=item[4]) for item in ranked)


def _gate_specs(lane: Lane) -> tuple[tuple[str, str, GateState], ...]:
    shared = tuple(("shared", key, GateState.PENDING) for key in sorted(SHARED_GATES))
    lane_items = tuple((lane.value, key, GateState.PENDING) for key in sorted(LANE_GATES[lane]))
    if lane is Lane.NAME:
        lane_items = tuple(
            (group, key, GateState.PASSED if key == "name_quality" else state)
            for group, key, state in lane_items
        )
    return (*shared, *lane_items)


async def persist_inventory_lanes(
    session: AsyncSession,
    *,
    name_candidates: tuple[NameInventoryCandidate, ...],
    authority_records: list[TopDomainRecord],
    feed_by_domain: dict[str, DropCatchListing],
    observed_at: dt.datetime,
) -> dict[str, int]:
    config_row, config = await get_active_config(session)
    domains = {item.listing.domain for item in name_candidates}
    domains.update(record.domain for record in authority_records)
    if not domains:
        return {"name": 0, "authority": 0, "promoted": 0}

    rows = (
        await session.execute(select(Candidate).where(Candidate.domain.in_(sorted(domains))))
    ).scalars().all()
    candidates = {row.domain: row for row in rows}
    for domain in sorted(domains):
        candidate = candidates.get(domain)
        if candidate is None:
            candidate = Candidate(domain=domain, first_observed=observed_at)
            session.add(candidate)
            candidates[domain] = candidate
        candidate.last_observed = observed_at
        if candidate.availability_confidence != "authoritative":
            candidate.current_status = "pending_delete"
            candidate.availability_confidence = "probable"
        candidate.lifecycle_state = "pending_delete"
    await session.flush()

    candidate_ids = [candidate.id for candidate in candidates.values()]
    existing_assessments = (
        (
            await session.execute(
                select(LaneAssessment).where(
                    LaneAssessment.candidate_id.in_(candidate_ids),
                    LaneAssessment.config_version == config_row.version,
                )
            )
        )
        .scalars()
        .all()
    )
    assessments = {(row.candidate_id, row.lane): row for row in existing_assessments}
    gate_rows = (
        await session.execute(
            select(GateResult.candidate_id, GateResult.lane, GateResult.gate_key).where(
                GateResult.candidate_id.in_(candidate_ids),
                GateResult.config_version == config_row.version,
            )
        )
    ).all()
    existing_gates: set[tuple[int, str, str]] = {
        (int(row[0]), str(row[1]), str(row[2])) for row in gate_rows
    }
    promoted_count = 0

    def ensure_lane(
        *,
        candidate: Candidate,
        lane: Lane,
        model_version: str,
        score: float | None,
        subtype: str | None,
        signals: dict[str, Any],
        reasons: tuple[str, ...],
        missing: tuple[str, ...],
    ) -> None:
        nonlocal promoted_count
        key = (candidate.id, lane.value)
        assessment = assessments.get(key)
        is_new = assessment is None
        if assessment is None:
            assessment = LaneAssessment(
                candidate_id=candidate.id,
                lane=lane.value,
                state="research",
                screen_passed=True,
                model_version=model_version,
                config_version=config_row.version,
            )
            session.add(assessment)
            assessments[key] = assessment
        assessment.state = "research"
        assessment.screen_passed = True
        assessment.lane_score = score
        assessment.model_version = model_version
        assessment.name_subtype = subtype
        assessment.signals = signals
        assessment.reasons = list(reasons)
        assessment.missing_evidence = list(missing)
        assessment.computed_at = observed_at
        if candidate.promoted_at is None:
            candidate.promoted_at = observed_at
            candidate.review_state = "research"
        if is_new:
            promoted_count += 1
            session.add(
                CandidateEvent(
                    candidate_id=candidate.id,
                    event_type="candidate.promoted",
                    payload={"domain": candidate.domain, "lane": lane.value},
                    config_version=config_row.version,
                )
            )
        for group, gate_key, gate_state in _gate_specs(lane):
            gate_identity = (candidate.id, group, gate_key)
            if gate_identity in existing_gates:
                continue
            session.add(
                GateResult(
                    candidate_id=candidate.id,
                    lane=group,
                    gate_key=gate_key,
                    state=gate_state.value,
                    fatal=False,
                    config_version=config_row.version,
                    details=(
                        "deterministic subtype screen passed"
                        if gate_key == "name_quality"
                        else None
                    ),
                )
            )
            existing_gates.add(gate_identity)

    for item in name_candidates:
        result = item.assessment
        ensure_lane(
            candidate=candidates[item.listing.domain],
            lane=Lane.NAME,
            model_version=result.model_version,
            score=result.score,
            subtype=result.subtype.value if result.subtype else None,
            signals={"tokens": list(result.tokens), "source": "full_expiry_inventory"},
            reasons=result.reasons,
            missing=("domain-specific comparable sales", "buyer thesis", "rights clearance"),
        )

    for record in authority_records:
        candidate = candidates[record.domain]
        candidate.open_pagerank = record.open_pagerank
        candidate.referring_domains = record.referring_domains
        candidate.authority_rank = record.rank
        candidate.authority_source = "openpagerank_top10m"
        candidate.authority_observed_at = observed_at
        result = screen_authority(
            AuthorityScreenInput(
                domain=record.domain,
                referring_domains=record.referring_domains,
                open_pagerank=record.open_pagerank,
                minimum_referring_domains=config.authority.prefilter_min_referring_domains,
            )
        )
        if result.screen_passed:
            ensure_lane(
                candidate=candidate,
                lane=Lane.AUTHORITY,
                model_version=result.model_version,
                score=result.score,
                subtype=None,
                signals={
                    "provider": "openpagerank",
                    "referring_domains": record.referring_domains,
                    "rank": record.rank,
                },
                reasons=result.reasons,
                missing=result.missing_evidence,
            )

    # Store pending-delete watch provenance for Name-only discoveries too. This
    # is explicitly watch evidence, never a purchase or backorder instruction.
    external_keys = [feed_by_domain[domain].external_key for domain in domains]
    existing_listings = (
        (
            await session.execute(
                select(MarketplaceListing).where(
                    MarketplaceListing.marketplace == "dropcatch",
                    MarketplaceListing.external_key.in_(external_keys),
                )
            )
        )
        .scalars()
        .all()
    )
    listings = {row.external_key: row for row in existing_listings}
    for domain in domains:
        feed = feed_by_domain[domain]
        listing = listings.get(feed.external_key)
        if listing is None:
            session.add(
                MarketplaceListing(
                    candidate_id=candidates[domain].id,
                    marketplace="dropcatch",
                    external_key=feed.external_key,
                    acquisition_type="watch_only",
                    listing_status="pending_delete",
                    drop_date=feed.drop_date,
                    listing_url=feed.listing_url,
                    first_seen=observed_at,
                    last_seen=observed_at,
                    raw_response={"record_type": feed.record_type},
                )
            )
        else:
            listing.last_seen = observed_at
            listing.drop_date = feed.drop_date

    return {
        "name": len(name_candidates),
        "authority": len(authority_records),
        "promoted": promoted_count,
    }
