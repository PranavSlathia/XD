"""GHArchive BigQuery sampler — for the Phase 1 A2 worker (not the spike).

The spike uses GitHub Search API for simplicity. This module provides the
production sampler that filters by recent PushEvent / CreateEvent activity
on high-star repos, sourced from `githubarchive.day.YYYYMMDD`.

Cost-controlled via `maximum_bytes_billed`.
"""
from __future__ import annotations

import datetime as dt

from dh.config import settings
from dh.sources.github.repos import Repo

# `bigquery-public-data.github_repos.sample_repos` carries `watch_count` for
# every indexed repo. Combined with GHArchive's daily event table, we can
# answer: "repos with ≥N stars that pushed in the last K days".
_QUERY_TEMPLATE = """
WITH active_repos AS (
  SELECT repo.name AS repo_name
  FROM `githubarchive.day.{date_yyyymmdd}`
  WHERE type IN ('PushEvent', 'CreateEvent')
  GROUP BY repo.name
)
SELECT s.repo_name, s.watch_count
FROM `bigquery-public-data.github_repos.sample_repos` AS s
JOIN active_repos AS a USING (repo_name)
WHERE s.watch_count >= @star_floor
ORDER BY s.watch_count DESC
LIMIT @max_repos
"""


async def sample_active_high_star_repos(
    *,
    date: dt.date | None = None,
    star_floor: int = 500,
    max_repos: int = 2000,
) -> list[Repo]:
    """Query GHArchive for repos with recent activity AND high stars.

    NOTE: Stub. BigQuery integration deferred until Phase 1; the spike
    uses dh.sources.github.search.sample_high_star_repos instead.
    """
    _ = (date, star_floor, max_repos, settings.bigquery_project)  # silence-unused
    raise NotImplementedError(
        "GHArchive BigQuery sampler reserved for Phase 1. "
        "Spike uses dh.sources.github.search.sample_high_star_repos."
    )


def render_sql(date: dt.date, star_floor: int, max_repos: int) -> str:
    """Render the parametrised query for review / dry-run."""
    return _QUERY_TEMPLATE.format(date_yyyymmdd=date.strftime("%Y%m%d")).replace(
        "@star_floor", str(star_floor)
    ).replace("@max_repos", str(max_repos))
