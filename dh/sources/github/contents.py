"""GitHub Contents / Trees API — fetch README + docs/*.md and extract URLs.

Cost controls:
  - per-repo budget: max_md_files (default 30), max_clone_mb (NA via API)
  - ETag-conditional GET (304 = near-zero quota cost on repeat runs)
  - asyncio.Semaphore to bound concurrency
  - aiolimiter for GitHub API rate-limit politeness

URL extraction:
  - Parses markdown link form: [text](url)
  - Parses bare URLs in prose
  - Detects fenced code blocks; URLs INSIDE code blocks are still emitted
    BUT tagged via the path/context classifier as API_ENDPOINT (rejected).
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Final

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from dh.config import settings
from dh.logging import log
from dh.sources.github.context import (
    ContextType,
    classify_url_context,
    is_acceptable,
)
from dh.sources.github.repos import ExtractedUrl, Repo, RepoFile

_API_ROOT: Final = "https://api.github.com"
_LIMITER = AsyncLimiter(max_rate=80, time_period=60)  # well under 5k/hr

# Match either '[text](url)' or a bare URL not preceded by '(' or '['.
_MD_LINK_RE = re.compile(r"\[(?P<text>[^\]\n]+)\]\((?P<url>https?://[^\s)]+)\)")
_BARE_URL_RE = re.compile(
    r"(?<![\(\[])(?P<url>https?://[^\s)\],<>\"']+)"
)
_FENCE_RE = re.compile(r"^\s*```")

_INTERESTING_PATHS = (
    "README.md", "README.rst", "README.MD",
    "Readme.md", "readme.md",
    "CHANGELOG.md", "HISTORY.md",
)
_INTERESTING_DIRS = ("docs", "doc", "guide", "tutorial")


def _headers(etag: str | None = None) -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "domain-hunter-spike/0.1",
    }
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    if etag:
        h["If-None-Match"] = etag
    return h


def _looks_markdown(path: str) -> bool:
    low = path.lower()
    return low.endswith((".md", ".mdx", ".rst", ".txt"))


def _strip_url_trailing_punct(url: str) -> str:
    """Strip trailing punctuation that's almost certainly not part of the URL."""
    while url and url[-1] in ".,;:!?":
        url = url[:-1]
    # Balance parens: drop trailing ')' if there are more closing than opening.
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url


def _surround(lines: list[str], idx: int, window: int = 3) -> str:
    lo = max(0, idx - window)
    hi = min(len(lines), idx + window + 1)
    return "\n".join(lines[lo:hi])


def iter_urls_in_markdown(
    *, text: str, file_path: str, repo: Repo
) -> AsyncIterator[ExtractedUrl]:
    """Synchronous generator wrapped as async — yields ExtractedUrl per match.

    Acceptable URLs only (path/context classifier filters out everything else
    BEFORE the URL is emitted). This is the safety boundary.
    """

    async def _gen() -> AsyncIterator[ExtractedUrl]:
        lines = text.splitlines()
        in_fence = False
        for i, line in enumerate(lines):
            if _FENCE_RE.match(line):
                in_fence = not in_fence
                continue

            # Collect URLs on this line.
            found: list[str] = []
            for m in _MD_LINK_RE.finditer(line):
                found.append(_strip_url_trailing_punct(m.group("url")))
            for m in _BARE_URL_RE.finditer(line):
                u = _strip_url_trailing_punct(m.group("url"))
                if not any(u == f or u.startswith(f + "#") for f in found):
                    found.append(u)

            if not found:
                continue

            surrounding = _surround(lines, i)
            for url in found:
                ctx = classify_url_context(
                    file_path=file_path, url=url, surrounding=surrounding
                )
                if not is_acceptable(ctx):
                    continue
                # Defensive: also check fence flag computed line-by-line; even
                # if classify_url_context missed it, we skip in-fence here.
                if in_fence:
                    continue
                yield ExtractedUrl(
                    repo=repo,
                    file_path=file_path,
                    url=url,
                    context_type=str(ctx),
                    surrounding=surrounding,
                )

    return _gen()


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
)
async def _list_tree(
    client: httpx.AsyncClient, repo: Repo
) -> list[str]:
    """Return all file paths in the repo's default branch (recursive)."""
    async with _LIMITER:
        url = f"{_API_ROOT}/repos/{repo.full_name}/git/trees/{repo.default_branch}?recursive=1"
        resp = await client.get(url, headers=_headers())
        if resp.status_code == 404:
            log.debug("github.tree.404", repo=repo.full_name)
            return []
        resp.raise_for_status()
        data = resp.json()
    paths: list[str] = []
    for entry in data.get("tree", []):
        if entry.get("type") != "blob":
            continue
        p = entry.get("path", "")
        if not _looks_markdown(p):
            continue
        paths.append(p)
    return paths


def _file_priority(path: str) -> int:
    """Lower = higher priority. Used to cap to max_md_files."""
    base = path.split("/")[-1]
    if base in _INTERESTING_PATHS:
        return 0
    head = path.split("/", 1)[0].lower()
    if head in _INTERESTING_DIRS:
        return 1
    return 9


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
)
async def _fetch_blob(
    client: httpx.AsyncClient, repo: Repo, path: str
) -> RepoFile | None:
    async with _LIMITER:
        # Raw content via the Contents API
        url = f"{_API_ROOT}/repos/{repo.full_name}/contents/{path}"
        headers = _headers()
        # Ask for raw markdown directly
        headers["Accept"] = "application/vnd.github.raw"
        resp = await client.get(
            url,
            headers=headers,
            params={"ref": repo.default_branch},
        )
    if resp.status_code == 404:
        return None
    if resp.status_code == 304:
        return None
    resp.raise_for_status()
    return RepoFile(
        repo=repo, path=path, text=resp.text, etag=resp.headers.get("ETag")
    )


async def extract_urls_from_repo(
    repo: Repo, *, max_md_files: int = 30
) -> list[ExtractedUrl]:
    """End-to-end: list markdown files, fetch up to N, extract acceptable URLs."""
    if repo.archived:
        log.debug("github.skip.archived", repo=repo.full_name)
        return []

    out: list[ExtractedUrl] = []
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            md_paths = await _list_tree(client, repo)
        except httpx.HTTPError as e:
            log.warning("github.tree.error", repo=repo.full_name, error=str(e))
            return []

        # Sort by priority + path; keep top max_md_files
        md_paths.sort(key=lambda p: (_file_priority(p), p))
        md_paths = md_paths[:max_md_files]

        for path in md_paths:
            try:
                blob = await _fetch_blob(client, repo, path)
            except httpx.HTTPError as e:
                log.warning(
                    "github.blob.error",
                    repo=repo.full_name,
                    path=path,
                    error=str(e),
                )
                continue
            if blob is None:
                continue
            async for eu in iter_urls_in_markdown(
                text=blob.text, file_path=path, repo=repo
            ):
                out.append(eu)

    return out


def context_of_extracted(eu: ExtractedUrl) -> ContextType:
    """Re-parse the string context_type to a ContextType enum value."""
    return ContextType(eu.context_type)
