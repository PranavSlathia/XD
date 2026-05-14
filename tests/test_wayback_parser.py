"""Tests for the deterministic CDX row parser."""
from __future__ import annotations

from dh.sources.wayback.cdx import _parse_row


def test_parse_row_basic() -> None:
    headers = ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"]
    row = [
        "com,example)/index.html",
        "20100101000000",
        "https://example.com/index.html",
        "text/html",
        "200",
        "abc123",
        "1024",
    ]
    e = _parse_row(headers, row)
    assert e is not None
    assert e.urlkey == "com,example)/index.html"
    assert e.timestamp == "20100101000000"
    assert e.original == "https://example.com/index.html"
    assert e.statuscode == 200
    assert e.length == 1024


def test_parse_row_handles_dash_statuscode() -> None:
    headers = ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"]
    row = ["k", "20100101000000", "https://example.com/", "warc/revisit", "-", "abc", "-"]
    e = _parse_row(headers, row)
    assert e is not None
    assert e.statuscode is None
    assert e.length is None


def test_parse_row_missing_required_returns_none() -> None:
    headers = ["urlkey", "mimetype"]
    row = ["k", "text/html"]
    assert _parse_row(headers, row) is None
