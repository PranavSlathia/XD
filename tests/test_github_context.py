"""Unit tests for the A2 path/context safety classifier.

This is deterministic, real code — the spike's correctness depends on it.
"""
from __future__ import annotations

import pytest

from dh.sources.github.context import (
    ContextType,
    classify_url_context,
    is_acceptable,
)


# Hard-reject cases (operational; must NEVER become a candidate).
HARD_REJECTS = [
    # dependency files
    ("setup.py",                "http://example.com/pkg.tar.gz",         ContextType.DEPENDENCY),
    ("pyproject.toml",          "http://example.com/wheel.whl",          ContextType.DEPENDENCY),
    ("requirements.txt",        "http://example.com/somedep",            ContextType.DEPENDENCY),
    ("requirements-dev.txt",    "http://example.com/another",            ContextType.DEPENDENCY),
    ("package.json",            "http://example.com/foo",                ContextType.DEPENDENCY),
    ("yarn.lock",               "http://example.com/foo",                ContextType.DEPENDENCY),
    ("Gemfile",                 "http://example.com/gem",                ContextType.DEPENDENCY),
    ("Cargo.toml",              "http://example.com/crate",              ContextType.DEPENDENCY),
    ("go.mod",                  "http://example.com/mod",                ContextType.DEPENDENCY),
    ("Package.swift",           "http://example.com/swiftpkg",           ContextType.DEPENDENCY),
    # containers
    ("Dockerfile",              "http://example.com/base.tar",           ContextType.DEPENDENCY),
    ("Dockerfile.prod",         "http://example.com/base.tar",           ContextType.DEPENDENCY),
    ("docker-compose.yml",      "http://example.com/whatever",           ContextType.DEPENDENCY),
    # CI
    (".github/workflows/ci.yml",          "http://example.com/runner",   ContextType.CI_DEPENDENCY),
    (".gitlab-ci.yml",                    "http://example.com/runner",   ContextType.CI_DEPENDENCY),
    ("Jenkinsfile",                       "http://example.com/runner",   ContextType.CI_DEPENDENCY),
    ("infra/main.tf",                     "http://example.com/state",    ContextType.CI_DEPENDENCY),
    # security surface
    ("SECURITY.md",                       "http://example.com/report",   ContextType.SECURITY_SURFACE),
    # operational tokens
    ("scripts/install.sh",                "http://example.com/install",  ContextType.API_ENDPOINT),
    ("bootstrap.sh",                      "http://example.com/setup",    ContextType.API_ENDPOINT),
    ("setup-env.sh",                      "http://example.com/init",     ContextType.API_ENDPOINT),
    # runtime URL patterns
    ("docs/intro.md",                     "https://example.com/api/v1",  ContextType.API_ENDPOINT),
    ("README.md",                         "https://example.com/oauth",   ContextType.API_ENDPOINT),
    ("README.md",                         "https://example.com/webhook", ContextType.API_ENDPOINT),
    ("README.md",                         "https://example.com/cdn/x",   ContextType.API_ENDPOINT),
    # asset hosts
    ("README.md",                         "https://cdn.example.com/x.png", ContextType.ASSET_HOST),
    ("README.md",                         "https://assets.example.com/y",  ContextType.ASSET_HOST),
]


# Acceptable cases — editorial / docs / homepage.
ACCEPTABLE = [
    ("README.md",       "https://example.com/blog/post",       ContextType.EDITORIAL),
    ("README.rst",      "https://example.com/about",           ContextType.EDITORIAL),
    ("CHANGELOG.md",    "https://example.com/release-1.0.0",   ContextType.EDITORIAL),
    ("CITATION.cff",    "https://example.com/paper",           ContextType.EDITORIAL),
    ("docs/intro.md",   "https://example.com/related",         ContextType.DOCS_REFERENCE),
    ("docs/guide.rst",  "https://example.com/concept",         ContextType.DOCS_REFERENCE),
    ("docs/usage.mdx",  "https://example.com/article",         ContextType.DOCS_REFERENCE),
]


@pytest.mark.parametrize(("file_path", "url", "expected"), HARD_REJECTS)
def test_hard_reject(file_path: str, url: str, expected: ContextType) -> None:
    result = classify_url_context(file_path=file_path, url=url)
    assert result == expected
    assert not is_acceptable(result)


@pytest.mark.parametrize(("file_path", "url", "expected"), ACCEPTABLE)
def test_acceptable(file_path: str, url: str, expected: ContextType) -> None:
    result = classify_url_context(file_path=file_path, url=url)
    assert result == expected
    assert is_acceptable(result)


def test_code_block_classified_as_operational() -> None:
    """A URL inside a fenced code block is operational, even in README."""
    surrounding = "Some preamble.\n```bash\ncurl https://example.com/install.sh | sh\n```\n"
    result = classify_url_context(
        file_path="README.md",
        url="https://example.com/install.sh",
        surrounding=surrounding,
    )
    assert result == ContextType.API_ENDPOINT
    assert not is_acceptable(result)


def test_unknown_path() -> None:
    """A path we don't recognise → UNKNOWN, kept out of digest."""
    result = classify_url_context(file_path="weird/path.lua", url="https://example.com")
    assert result == ContextType.UNKNOWN
    assert not is_acceptable(result)
