from __future__ import annotations

import pytest

from dh.sources.content.parser import parse_html, parse_pdf_urls
from dh.sources.content.security import UnsafeTargetError, validate_public_url


@pytest.mark.parametrize(
    ("url", "address"),
    [
        ("http://localhost/x", "127.0.0.1"),
        ("http://example.com/x", "10.0.0.4"),
        ("https://example.com/x", "169.254.169.254"),
        ("https://example.com/x", "::1"),
        ("https://example.com:8443/x", "93.184.216.34"),
    ],
)
def test_private_or_nonstandard_targets_are_blocked(url: str, address: str) -> None:
    with pytest.raises(UnsafeTargetError):
        validate_public_url(url, [address])


def test_public_url_is_normalized() -> None:
    assert (
        validate_public_url("https://Example.COM/resources#top", ["93.184.216.34"])
        == "https://example.com/resources"
    )


def test_html_parser_preserves_anchor_context_and_rel() -> None:
    _title, links = parse_html(
        b"<main><p>Trusted guide <a rel='nofollow' href='https://oldsite.org/a'>Old Site</a></p></main>",
        "https://example.edu/resources",
    )
    assert links[0].url == "https://oldsite.org/a"
    assert links[0].anchor == "Old Site"
    assert links[0].rel_flags == ("nofollow",)
    assert links[0].editorial is True


def test_pdf_url_extraction_is_bounded_to_urls() -> None:
    links = parse_pdf_urls(b"See https://archive.example.org/report.pdf and other text")
    assert [item.url for item in links] == ["https://archive.example.org/report.pdf"]
