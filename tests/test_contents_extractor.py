"""Tests for the markdown URL extractor (deterministic + offline)."""
from __future__ import annotations

import asyncio

from dh.sources.github.contents import iter_urls_in_markdown
from dh.sources.github.repos import Repo

REPO = Repo(owner="acme", name="docs", stars=5000)


def _collect(text: str, file_path: str) -> list[tuple[str, str]]:
    async def _go() -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        async for eu in iter_urls_in_markdown(
            text=text, file_path=file_path, repo=REPO
        ):
            out.append((eu.url, eu.context_type))
        return out

    return asyncio.run(_go())


def test_basic_markdown_link_in_readme() -> None:
    md = "See the [docs](https://example.com/docs/intro) for details."
    out = _collect(md, "README.md")
    assert ("https://example.com/docs/intro", "editorial") in out


def test_url_in_code_block_is_dropped() -> None:
    md = (
        "Install via:\n"
        "```bash\n"
        "curl https://example.com/install.sh | sh\n"
        "```\n"
        "Project: https://example.com/about\n"
    )
    out = _collect(md, "README.md")
    urls = {u for u, _ in out}
    assert "https://example.com/install.sh" not in urls
    assert "https://example.com/about" in urls


def test_dependency_path_emits_nothing() -> None:
    # Even if there's a URL, it's dropped because the file is operational.
    md = "see https://example.com/pkg.tar.gz"
    assert _collect(md, "requirements.txt") == []
    assert _collect(md, "pyproject.toml") == []
    assert _collect(md, ".github/workflows/ci.yml") == []


def test_docs_md_emits_docs_reference() -> None:
    md = "Related work: https://example.com/related"
    out = _collect(md, "docs/intro.md")
    assert ("https://example.com/related", "docs_reference") in out


def test_trailing_punct_stripped() -> None:
    md = "Visit https://example.com/blog. Then read https://example.com/about,"
    out = _collect(md, "README.md")
    urls = {u for u, _ in out}
    assert "https://example.com/blog" in urls
    assert "https://example.com/about" in urls


def test_api_endpoint_in_readme_rejected() -> None:
    md = "Webhook: https://example.com/webhook/handler\nBlog: https://example.com/blog"
    out = _collect(md, "README.md")
    urls = {u for u, _ in out}
    assert "https://example.com/webhook/handler" not in urls
    assert "https://example.com/blog" in urls
