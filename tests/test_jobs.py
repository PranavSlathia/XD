from __future__ import annotations

from dh.jobs import SAFE_JOB_KINDS, should_throttle_load


def test_operator_load_guard_stops_before_three() -> None:
    assert should_throttle_load(2.8, 2.8) is True
    assert should_throttle_load(2.79, 2.8) is False


def test_operator_jobs_remain_typed_and_non_destructive() -> None:
    assert SAFE_JOB_KINDS == {
        "inventory_scan",
        "content_crawl",
        "availability_refresh",
        "backlink_validate",
        "wayback_refresh",
        "recompute_assessments",
        "generate_dossier",
    }
    forbidden = ("shell", "docker", "purchase", "register", "bid", "backorder")
    assert not any(word in kind for word in forbidden for kind in SAFE_JOB_KINDS)
