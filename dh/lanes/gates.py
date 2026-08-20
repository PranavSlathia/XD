"""Readiness policy shared by API, workers, and the XD client contract."""

from __future__ import annotations

from dataclasses import dataclass

from dh.lanes.types import GateState, Lane

SHARED_GATES = frozenset(
    {
        "availability_authoritative",
        "standard_registration_price",
        "rights_clear",
        "reputation_clean",
        "history_clean",
        "buyer_thesis",
    }
)
LANE_GATES: dict[Lane, frozenset[str]] = {
    Lane.NAME: frozenset({"name_quality", "domain_specific_comps"}),
    Lane.AUTHORITY: frozenset({"verified_referring_pages", "authority_rubric"}),
}


@dataclass(frozen=True, slots=True)
class GateEvidence:
    lane: str
    key: str
    state: GateState
    fatal: bool = False


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    ready_lanes: tuple[Lane, ...]
    pending: tuple[str, ...]
    failed: tuple[str, ...]
    fatal_failures: tuple[str, ...]


def evaluate_readiness(
    screened_lanes: set[Lane],
    gates: tuple[GateEvidence, ...] | list[GateEvidence],
) -> Readiness:
    latest = {(gate.lane, gate.key): gate for gate in gates}
    failed = sorted(
        f"{gate.lane}:{gate.key}" for gate in latest.values() if gate.state is GateState.FAIL
    )
    fatal = sorted(
        f"{gate.lane}:{gate.key}"
        for gate in latest.values()
        if gate.state is GateState.FAIL and gate.fatal
    )
    ready_lanes: list[Lane] = []
    pending: set[str] = set()

    for lane in sorted(screened_lanes, key=str):
        required = (("shared", key) for key in SHARED_GATES)
        lane_required = ((lane.value, key) for key in LANE_GATES[lane])
        lane_ok = not fatal
        for group, key in (*required, *lane_required):
            evidence = latest.get((group, key))
            if evidence is None or evidence.state is GateState.PENDING:
                pending.add(f"{group}:{key}")
                lane_ok = False
            elif evidence.state is GateState.FAIL:
                lane_ok = False
        if lane_ok:
            ready_lanes.append(lane)

    return Readiness(
        ready=bool(ready_lanes) and not fatal,
        ready_lanes=tuple(ready_lanes),
        pending=tuple(sorted(pending)),
        failed=tuple(failed),
        fatal_failures=tuple(fatal),
    )


def review_transition_allowed(current: str, requested: str) -> bool:
    """Reject is terminal until an operator records an explicit Research reopen."""

    return current != "reject" or requested == "research"
