from __future__ import annotations

import datetime as dt

import pytest

from dh.sources.registrar.core import TLD_ADAPTERS, adapter_for_domain
from dh.sources.registrar.porkbun import parse_quote_response


def test_core_six_have_explicit_lifecycle_adapters() -> None:
    assert set(TLD_ADAPTERS) == {"com", "net", "org", "co", "io", "ai"}
    assert adapter_for_domain("example.AI.").tld == "ai"


def test_unsupported_tld_is_rejected_before_provider_call() -> None:
    with pytest.raises(ValueError, match="unsupported TLD"):
        adapter_for_domain("example.xyz")


def test_standard_available_quote_is_current_and_normal() -> None:
    observed = dt.datetime(2026, 8, 21, 12, tzinfo=dt.UTC)
    result = parse_quote_response(
        "brightmarket.com",
        {
            "status": "SUCCESS",
            "response": {
                "avail": "yes",
                "type": "registration",
                "price": "11.08",
                "regularPrice": "11.08",
                "premium": "no",
                "additional": {
                    "renewal": {
                        "type": "renewal",
                        "price": "11.08",
                        "regularPrice": "11.08",
                    }
                },
            },
        },
        observed_at=observed,
    )

    assert result.availability_status == "available"
    assert result.price_class == "normal"
    assert result.quote_price_micros == 11_080_000
    assert result.renewal_price_micros == 11_080_000
    assert result.expires_at == observed + dt.timedelta(minutes=15)


@pytest.mark.parametrize(
    ("quote_type", "premium", "expected"),
    [
        ("registration", "yes", "premium"),
        ("auction", "no", "auction"),
        ("marketplace", "no", "aftermarket"),
    ],
)
def test_nonstandard_price_classes_are_never_normal(
    quote_type: str, premium: str, expected: str
) -> None:
    result = parse_quote_response(
        "valuable.ai",
        {
            "status": "SUCCESS",
            "response": {
                "avail": "yes",
                "type": quote_type,
                "price": "2500.00",
                "premium": premium,
            },
        },
    )
    assert result.availability_status == "available"
    assert result.price_class == expected


def test_unavailable_quote_clears_prices_and_fails_availability_only() -> None:
    result = parse_quote_response(
        "taken.org",
        {
            "status": "SUCCESS",
            "response": {
                "avail": "no",
                "type": "registration",
                "price": "7.98",
                "premium": "no",
            },
        },
    )
    assert result.availability_status == "unavailable"
    assert result.price_class == "unknown"
    assert result.quote_price_micros is None
    assert result.renewal_price_micros is None


def test_missing_premium_or_failed_provider_response_stays_unknown() -> None:
    missing_flag = parse_quote_response(
        "maybe.co",
        {
            "status": "SUCCESS",
            "response": {
                "avail": "yes",
                "type": "registration",
                "price": "29.00",
            },
        },
    )
    failed = parse_quote_response(
        "maybe.io",
        {
            "status": "ERROR",
            "response": {
                "avail": "yes",
                "type": "registration",
                "price": "29.00",
                "premium": "no",
            },
        },
    )
    assert missing_flag.availability_status == "available"
    assert missing_flag.price_class == "unknown"
    assert failed.availability_status == "unknown"
    assert failed.price_class == "unknown"

