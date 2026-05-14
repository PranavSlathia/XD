"""GitHub Search API repo sampler — used by the Phase 0.5 spike.

The Search API caps at 1,000 results per query, plenty for sampling 500–1,000
high-star repos. No GCP setup required (unlike GHArchive on BigQuery).

Authenticated rate limit: 30 search requests/minute = up to 3,000 repos/min.
"""
from __future__ import annotations

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
from dh.sources.github.repos import Repo

_SEARCH_URL = "https://api.github.com/search/repositories"
_LIMITER = AsyncLimiter(max_rate=20, time_period=60)  # under 30 rpm


def _headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "domain-hunter-spike/0.1",
    }
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
)
async def _search_page(
    client: httpx.AsyncClient,
    *,
    star_floor: int,
    page: int,
    pushed_before: str | None = None,
    extra_query: str | None = None,
) -> tuple[list[Repo], int]:
    async with _LIMITER:
        q_parts = [f"stars:>={star_floor}", "archived:false"]
        if pushed_before:
            q_parts.append(f"pushed:<{pushed_before}")
        if extra_query:
            q_parts.append(extra_query)
        params = {
            "q": " ".join(q_parts),
            "sort": "stars",
            "order": "desc",
            "per_page": 100,
            "page": page,
        }
        resp = await client.get(_SEARCH_URL, params=params, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
    repos: list[Repo] = []
    for item in data.get("items", []):
        owner_login = item.get("owner", {}).get("login")
        if not owner_login:
            continue
        repos.append(
            Repo(
                owner=owner_login,
                name=item["name"],
                stars=int(item.get("stargazers_count", 0)),
                archived=bool(item.get("archived", False)),
                default_branch=item.get("default_branch", "main"),
            )
        )
    total = int(data.get("total_count", 0))
    return repos, total


async def sample_high_star_repos(
    *,
    n: int = 500,
    star_floor: int = 5000,
    pushed_before: str | None = None,
    extra_query: str | None = None,
) -> list[Repo]:
    """Return up to `n` repos with stars >= `star_floor`, sorted by stars desc.

    Args:
        pushed_before: ISO date string; restricts to repos last pushed before this.
                       Useful for link-rot sampling (e.g. "2022-01-01").
        extra_query:   Raw GitHub-search qualifier appended to the query.
    """
    if not settings.github_token:
        log.warning(
            "github.search.no_token",
            note="unauthenticated calls are limited to ~10/min; set DH_GITHUB_TOKEN",
        )
    repos: list[Repo] = []
    async with httpx.AsyncClient(timeout=30) as client:
        page = 1
        while len(repos) < n and page <= 10:  # Search API caps at 1000 = 10 pages
            batch, total = await _search_page(
                client,
                star_floor=star_floor,
                page=page,
                pushed_before=pushed_before,
                extra_query=extra_query,
            )
            if not batch:
                break
            repos.extend(batch)
            log.debug(
                "github.search.page",
                page=page,
                got=len(batch),
                running_total=len(repos),
                api_total=total,
            )
            if len(batch) < 100:
                break
            page += 1
    # Dedupe + truncate
    seen: set[str] = set()
    out: list[Repo] = []
    for r in repos:
        if r.full_name in seen:
            continue
        seen.add(r.full_name)
        out.append(r)
        if len(out) >= n:
            break
    return out
