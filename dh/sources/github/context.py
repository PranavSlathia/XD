"""A2 path / context safety classifier.

PRD §4.1 — every URL extracted from a GitHub repo must be tagged with a
`context_type` BEFORE it can become a candidate. Operational dependencies
(install scripts, CI configs, package manifests, auth endpoints, etc.) are
hard-rejected — registering them would create a supply-chain-attack surface.

This module is deterministic. No LLM. Pure rules. Tested in tests/.

Inputs:
    file_path:      path inside the repo, e.g. "docs/README.md" or ".github/workflows/ci.yml"
    url:            the extracted URL
    surrounding:    a few lines of context around the URL (raw markdown / file content)

Output:
    ContextType — one of the PRD enum values
"""
from __future__ import annotations

import re
from enum import StrEnum
from pathlib import PurePosixPath


class ContextType(StrEnum):
    EDITORIAL          = "editorial"
    HOMEPAGE           = "homepage"
    DOCS_REFERENCE     = "docs_reference"
    DEPENDENCY         = "dependency"
    API_ENDPOINT       = "api_endpoint"
    ASSET_HOST         = "asset_host"
    SECURITY_SURFACE   = "security_surface"
    CI_DEPENDENCY      = "ci_dependency"
    UNKNOWN            = "unknown"


# --- File-path rules ---

_DEPENDENCY_FILENAMES: frozenset[str] = frozenset({
    "setup.py", "setup.cfg", "pyproject.toml",
    "requirements.txt", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Gemfile", "Gemfile.lock",
    "composer.json", "composer.lock",
    "Cargo.toml", "Cargo.lock",
    "go.mod", "go.sum",
    "Podfile", "Podfile.lock",
    "Package.swift", "Package.resolved",
    "build.gradle", "build.gradle.kts", "pom.xml",
    "mix.exs", "mix.lock",
    "stack.yaml", "cabal.project",
})

_DEPENDENCY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^requirements[-_].*\.txt$"),
    re.compile(r".*requirements\.in$"),
)

_CONTAINER_FILENAMES: frozenset[str] = frozenset({
    "Dockerfile", "Containerfile",
})

_CONTAINER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^Dockerfile(\..+)?$"),
    re.compile(r"^docker-compose.*\.ya?ml$"),
    re.compile(r"^compose.*\.ya?ml$"),
)

_CI_DIR_PREFIXES: tuple[str, ...] = (
    ".github/workflows/", ".github/actions/", ".gitlab/", ".circleci/",
    ".buildkite/", ".azure/", ".drone/",
)

_CI_FILENAMES: frozenset[str] = frozenset({
    ".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml",
    ".travis.yml", "appveyor.yml", "bitbucket-pipelines.yml",
})

_IAC_SUFFIXES: tuple[str, ...] = (".tf", ".tfvars")

_SECURITY_FILENAMES: frozenset[str] = frozenset({
    "SECURITY.md", "SECURITY.txt",
})

_OPERATIONAL_PATH_TOKENS: tuple[str, ...] = (
    "install", "bootstrap", "setup-", "entrypoint",
    "update", "heartbeat", "auth", "sso", "webhook", "callback", "health",
)

_EDITORIAL_FILENAMES: frozenset[str] = frozenset({
    "README.md", "README.rst", "README.txt", "README",
    "CHANGELOG.md", "CHANGELOG.rst", "HISTORY.md",
    "CONTRIBUTORS.md", "AUTHORS.md", "MAINTAINERS.md",
    "CITATION.cff",
})


# --- URL-path rules ---

_RUNTIME_URL_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/api/"),
    re.compile(r"/oauth"),
    re.compile(r"/auth/"),
    re.compile(r"/sso/"),
    re.compile(r"/\.well-known/"),
    re.compile(r"/webhook"),
    re.compile(r"/cdn/"),
    re.compile(r"/track\b"),
    re.compile(r"/pixel\b"),
    re.compile(r"/check-update"),
    re.compile(r"/heartbeat"),
    re.compile(r"/healthz?\b"),
)

_ASSET_URL_HOST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^cdn\."),
    re.compile(r"^assets\."),
    re.compile(r"^static\."),
    re.compile(r"^img\."),
)


# --- Markdown context rules ---

_CODE_FENCE_PATTERN = re.compile(r"^\s*```")


def _is_in_code_block(surrounding: str | None, url: str | None = None) -> bool:
    """Check whether `url` sits inside a fenced code block within `surrounding`.

    Walks lines tracking fence open/close state. When we hit the line that
    contains the URL, return the current fence state.

    If `url` is None or not found in `surrounding`, fall back conservatively:
    if ANY fence is present in the surrounding, treat the URL as operational.
    """
    if not surrounding:
        return False
    in_fence = False
    for line in surrounding.splitlines():
        if _CODE_FENCE_PATTERN.match(line):
            in_fence = not in_fence
            continue
        if url and url in line:
            return in_fence
    return "```" in surrounding


# --- Classifier ---

def classify_url_context(
    *, file_path: str, url: str, surrounding: str | None = None
) -> ContextType:
    """Classify a single URL extracted from a GitHub repo file.

    Order matters — first match wins.
    """
    pp = PurePosixPath(file_path)
    name = pp.name
    parts = pp.parts
    lower_path = file_path.lower()
    lower_url = url.lower()

    # --- Hard rejects (operational dependencies / endpoints / assets) ---

    if name in _DEPENDENCY_FILENAMES or any(p.match(name) for p in _DEPENDENCY_PATTERNS):
        return ContextType.DEPENDENCY

    if name in _CONTAINER_FILENAMES or any(p.match(name) for p in _CONTAINER_PATTERNS):
        return ContextType.DEPENDENCY

    if name in _SECURITY_FILENAMES:
        return ContextType.SECURITY_SURFACE

    if any(file_path.startswith(prefix) for prefix in _CI_DIR_PREFIXES):
        return ContextType.CI_DEPENDENCY
    if name in _CI_FILENAMES:
        return ContextType.CI_DEPENDENCY
    if any(name.endswith(s) for s in _IAC_SUFFIXES):
        return ContextType.CI_DEPENDENCY

    if any(tok in lower_path for tok in _OPERATIONAL_PATH_TOKENS):
        return ContextType.API_ENDPOINT

    for pat in _RUNTIME_URL_PATH_PATTERNS:
        if pat.search(lower_url):
            return ContextType.API_ENDPOINT

    # Asset hosts
    try:
        host = re.sub(r"^https?://", "", url).split("/", 1)[0].lower()
    except (IndexError, ValueError):
        host = ""
    if any(pat.search(host) for pat in _ASSET_URL_HOST_PATTERNS):
        return ContextType.ASSET_HOST

    # Inside a fenced code block → almost certainly operational
    if _is_in_code_block(surrounding, url):
        return ContextType.API_ENDPOINT

    # --- Allows ---

    if name in _EDITORIAL_FILENAMES:
        return ContextType.EDITORIAL

    # docs/**/*.md prose
    if (
        len(parts) >= 2
        and parts[0].lower() == "docs"
        and name.lower().endswith((".md", ".rst", ".mdx", ".txt"))
    ):
        return ContextType.DOCS_REFERENCE

    return ContextType.UNKNOWN


# Contexts that may become candidates.
ACCEPTABLE_CONTEXTS: frozenset[ContextType] = frozenset({
    ContextType.EDITORIAL,
    ContextType.HOMEPAGE,
    ContextType.DOCS_REFERENCE,
})


def is_acceptable(context: ContextType) -> bool:
    return context in ACCEPTABLE_CONTEXTS
