"""Tests for the deterministic helpers inside dh.sources.rdap.client."""

from __future__ import annotations

from typing import Any, cast

from dh.sources.rdap.client import (
    _coerce_registrar,
    _epp_to_status,
    _tld_of,
    _whoisjson_status,
)
from dh.workers.rdap import _expiry_to_date


def test_expiry_date_parser() -> None:
    assert str(_expiry_to_date("2027-01-02T03:04:05Z")) == "2027-01-02"
    assert str(_expiry_to_date("2027-01-02")) == "2027-01-02"
    assert _expiry_to_date("not-a-date") is None


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


def test_epp_to_status_tolerates_non_string_element() -> None:
    # A malformed RDAP/WhoisJSON status array may contain a nested list.
    # The mapper must coerce, not raise AttributeError on `.lower()`.
    assert _epp_to_status(["active", cast(Any, ["nested"])]) == "registered"


# --------------------------------------------------------------------------- #
# _coerce_registrar — registrar may arrive as str / dict / list / None.
# Real-world: WhoisJSON returns registrar as an object
# {'id': None, 'name': 'Webnic', 'email': None, 'url': None}; RDAP jCard `fn`
# values are usually strings but some servers return lists.
# --------------------------------------------------------------------------- #


def test_coerce_registrar_plain_string() -> None:
    assert _coerce_registrar("GoDaddy.com, LLC") == "GoDaddy.com, LLC"


def test_coerce_registrar_dict_uses_name() -> None:
    obj = {"id": None, "name": "Webnic", "email": None, "url": None}
    assert _coerce_registrar(obj) == "Webnic"


def test_coerce_registrar_dict_falls_back_to_fn() -> None:
    assert _coerce_registrar({"fn": "Gandi SAS"}) == "Gandi SAS"


def test_coerce_registrar_list_takes_first_usable() -> None:
    assert _coerce_registrar(["MarkMonitor Inc.", "ignored"]) == "MarkMonitor Inc."


def test_coerce_registrar_none_and_empty() -> None:
    assert _coerce_registrar(None) is None
    assert _coerce_registrar([]) is None
    assert _coerce_registrar({}) is None
    assert _coerce_registrar("") is None
    assert _coerce_registrar("   ") is None


def test_coerce_registrar_unknown_scalar_is_none() -> None:
    assert _coerce_registrar(12345) is None


# --------------------------------------------------------------------------- #
# _whoisjson_status — WhoisJSON 'status' is normally "available"/"registered"
# but some responses return a list of EPP status codes. Must never crash.
# --------------------------------------------------------------------------- #


def test_whoisjson_status_string() -> None:
    assert _whoisjson_status({"status": "Available"}) == "available"
    assert _whoisjson_status({"status": "registered"}) == "registered"


def test_whoisjson_status_list_means_registered() -> None:
    obj: dict[str, object] = {"status": ["clientTransferProhibited", "clientDeleteProhibited"]}
    assert _whoisjson_status(obj) == "registered"


def test_whoisjson_status_empty_or_missing() -> None:
    assert _whoisjson_status({"status": []}) == ""
    assert _whoisjson_status({"status": None}) == ""
    assert _whoisjson_status({}) == ""
