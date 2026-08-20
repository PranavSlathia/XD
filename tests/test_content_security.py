from __future__ import annotations

import httpx
import pytest

from dh.sources.content.crawler import _fetch, prioritized_external_domains
from dh.sources.content.parser import ExtractedLink, parse_html, parse_pdf_urls
from dh.sources.content.security import UnsafeTargetError, validate_public_url
from dh.sources.content.validator import matching_target_link


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


def test_direct_link_validation_matches_registrable_target_domain() -> None:
    link = ExtractedLink(
        url="https://www.plainname.org/research#citation",
        anchor="Plain Name",
        context="Independent editorial citation",
        rel_flags=(),
        semantic_location="article",
        editorial=True,
    )

    assert matching_target_link((link,), "plainname.org") == link
    assert matching_target_link((link,), "another.org") is None


def test_content_discovery_prioritizes_editorial_core_tld_targets() -> None:
    links = (
        ExtractedLink(
            url="https://navigation.com/",
            anchor="Navigation",
            context=None,
            rel_flags=("nofollow",),
            semantic_location="nav",
            editorial=False,
        ),
        ExtractedLink(
            url="https://citation.org/report",
            anchor="Citation",
            context="Useful independent resource",
            rel_flags=(),
            semantic_location="article",
            editorial=True,
        ),
        ExtractedLink(
            url="https://www.seedexample.org/internal",
            anchor="Internal",
            context=None,
            rel_flags=(),
            semantic_location="article",
            editorial=True,
        ),
        ExtractedLink(
            url="https://unsupported.dev/",
            anchor="Unsupported",
            context=None,
            rel_flags=(),
            semantic_location="article",
            editorial=True,
        ),
    )

    assert prioritized_external_domains(
        links,
        source_url="https://seedexample.org/resources",
        core_tlds=("com", "org"),
        limit=2,
    ) == ("citation.org", "navigation.com")


@pytest.mark.asyncio
async def test_crawler_revalidates_cached_etag_without_downloading_body() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["etag"] = request.headers.get("If-None-Match")
        return httpx.Response(304, headers={"ETag": '"revision-2"'})

    async def resolver(_hostname: str) -> tuple[str, ...]:
        return ("93.184.216.34",)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetched = await _fetch(
            client,
            "https://example.com/resources",
            resolver=resolver,
            max_bytes=100_000,
            timeout_seconds=5,
            etag='"revision-2"',
        )

    assert seen["etag"] == '"revision-2"'
    assert fetched.status == 304
    assert fetched.content == b""
