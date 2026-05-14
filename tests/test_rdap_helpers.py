"""Tests for the deterministic helpers inside dh.sources.rdap.client."""
from __future__ import annotations

from dh.sources.rdap.client import _epp_to_status, _tld_of


def test_tld_of() -> None:
    assert _tld_of("example.com") == "com"
    assert _tld_of("subdomain.example.io") == "io"
    assert _tld_of("EXAMPLE.AI") == "ai"


def test_epp_to_status_pending_delete() -> None:
    assert _epp_to_status(["pending delete"]) == "pending_delete"
    assert _epp_to_status(["pendingDelete"]) == "pending_delete"


def test_epp_to_status_redemption() -> None:
    assert _epp_to_status(["redemption period"]) == "redemption_period"
    assert _epp_to_status(["RedemptionPeriod"]) == "redemption_period"


def test_epp_to_status_client_hold() -> None:
    assert _epp_to_status(["client hold"]) == "client_hold"


def test_epp_to_status_default_registered() -> None:
    assert _epp_to_status([]) == "registered"
    assert _epp_to_status(["active"]) == "registered"
    assert _epp_to_status(["clientTransferProhibited"]) == "registered"
