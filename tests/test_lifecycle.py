from __future__ import annotations

from dh.lanes.gates import review_transition_allowed
from dh.workers.rdap import lifecycle_from_status


def test_authoritative_status_maps_to_independent_lifecycle_state() -> None:
    assert lifecycle_from_status("registered") == "registered"
    assert lifecycle_from_status("expiring_soon") == "expiring_soon"
    assert lifecycle_from_status("redemption_period") == "redemption_period"
    assert lifecycle_from_status("pending_delete") == "pending_delete"
    assert lifecycle_from_status("available") == "available"


def test_unknown_status_does_not_erase_last_lifecycle_evidence() -> None:
    assert lifecycle_from_status("unknown") is None


def test_reject_requires_an_explicit_research_reopen() -> None:
    assert review_transition_allowed("reject", "research") is True
    assert review_transition_allowed("reject", "ready") is False
    assert review_transition_allowed("reject", "reject") is False
    assert review_transition_allowed("research", "ready") is True
