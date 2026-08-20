"""Direct, SSRF-safe validation of backlink-provider referring pages."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import tldextract
from sqlalchemy import select

from dh.db.engine import session_scope
from dh.db.models import LinkObservation, SourcePage
from dh.engine.configuration import get_active_config
from dh.sources.content.crawler import _fetch, _robots_allows
from dh.sources.content.parser import ExtractedLink, parse_html, parse_pdf_urls
from dh.sources.content.security import Resolver, system_resolver

_extract = tldextract.TLDExtract(suffix_list_urls=())


@dataclass(frozen=True, slots=True)
class ValidationTarget:
    observation_id: int
    source_page_id: int
    source_url: str
    target_domain: str
    etag: str | None
    was_live: bool | None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    target: ValidationTarget
    status: int | None
    content_type: str | None
    etag: str | None
    content_hash: bytes | None
    title: str | None
    matched_link: ExtractedLink | None
    unchanged: bool = False
    blocked: bool = False
    error: str | None = None


def registrable_domain(value: str) -> str | None:
    host = urlsplit(value).hostname or value
    parsed = _extract(host.lower().rstrip("."))
    if not parsed.domain or not parsed.suffix:
        return None
    return f"{parsed.domain}.{parsed.suffix}"


def matching_target_link(
    links: tuple[ExtractedLink, ...], target_domain: str
) -> ExtractedLink | None:
    normalized_target = registrable_domain(target_domain)
    if normalized_target is None:
        return None
    return next(
        (item for item in links if registrable_domain(item.url) == normalized_target),
        None,
    )


async def _validate_one(
    client: httpx.AsyncClient,
    target: ValidationTarget,
    *,
    resolver: Resolver,
    max_bytes: int,
    timeout_seconds: float,
) -> ValidationResult:
    try:
        if not await _robots_allows(
            client,
            target.source_url,
            resolver=resolver,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
        ):
            return ValidationResult(
                target=target,
                status=None,
                content_type=None,
                etag=target.etag,
                content_hash=None,
                title=None,
                matched_link=None,
                blocked=True,
            )
        fetched = await _fetch(
            client,
            target.source_url,
            resolver=resolver,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
            etag=target.etag,
        )
        if fetched.status == 304:
            return ValidationResult(
                target=target,
                status=304,
                content_type=fetched.content_type,
                etag=fetched.etag,
                content_hash=None,
                title=None,
                matched_link=None,
                unchanged=True,
            )
        title: str | None = None
        links: tuple[ExtractedLink, ...] = ()
        if 200 <= fetched.status < 300:
            if fetched.content_type == "text/html":
                title, links = parse_html(fetched.content, fetched.url)
            elif fetched.content_type == "application/pdf":
                links = parse_pdf_urls(fetched.content)
        return ValidationResult(
            target=target,
            status=fetched.status,
            content_type=fetched.content_type,
            etag=fetched.etag,
            content_hash=hashlib.sha256(fetched.content).digest(),
            title=title,
            matched_link=matching_target_link(links, target.target_domain),
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        return ValidationResult(
            target=target,
            status=None,
            content_type=None,
            etag=target.etag,
            content_hash=None,
            title=None,
            matched_link=None,
            error=f"{type(exc).__name__}: {exc}"[:500],
        )


async def validate_candidate_links(
    candidate_id: int,
    *,
    limit: int = 20,
    resolver: Resolver = system_resolver,
) -> dict[str, int]:
    """Re-fetch bounded referring pages and record whether the link is still live.

    Provider output only supplies targets for this operation. A link becomes
    current evidence only when this validator observes it in the fetched page.
    Network failures and robots denials remain unknown rather than becoming
    negative evidence.
    """

    if limit <= 0:
        return {
            "checked": 0,
            "live": 0,
            "removed": 0,
            "unchanged": 0,
            "robots_blocked": 0,
            "errors": 0,
        }

    async with session_scope() as session:
        _config_row, config = await get_active_config(session)
        rows = (
            await session.execute(
                select(LinkObservation, SourcePage)
                .join(SourcePage, SourcePage.id == LinkObservation.source_page_id)
                .where(LinkObservation.candidate_id == candidate_id)
                .order_by(
                    LinkObservation.currently_live.asc().nullsfirst(),
                    LinkObservation.last_seen.desc(),
                )
                .limit(max(1, min(limit, 100)))
            )
        ).all()
        targets = tuple(
            ValidationTarget(
                observation_id=observation.id,
                source_page_id=page.id,
                source_url=page.url,
                target_domain=observation.target_domain,
                etag=page.etag,
                was_live=observation.currently_live,
            )
            for observation, page in rows
        )
        max_bytes = config.crawler.max_response_bytes
        timeout_seconds = config.crawler.request_timeout_seconds
        minimum_delay = config.crawler.minimum_delay_seconds

    results: list[ValidationResult] = []
    async with httpx.AsyncClient(http2=True) as client:
        for index, target in enumerate(targets):
            results.append(
                await _validate_one(
                    client,
                    target,
                    resolver=resolver,
                    max_bytes=max_bytes,
                    timeout_seconds=timeout_seconds,
                )
            )
            if index + 1 < len(targets):
                await asyncio.sleep(minimum_delay)

    live = removed = unchanged = blocked = errors = 0
    now = dt.datetime.now(dt.UTC)
    async with session_scope() as session:
        for result in results:
            observation = await session.get(LinkObservation, result.target.observation_id)
            page = await session.get(SourcePage, result.target.source_page_id)
            if observation is None or page is None:
                continue
            if result.error is not None:
                errors += 1
                continue
            if result.blocked:
                blocked += 1
                continue
            page.last_seen = now
            if result.unchanged:
                unchanged += 1
                if result.target.was_live is True:
                    observation.last_seen = now
                continue
            page.http_status = result.status
            page.content_type = result.content_type
            page.etag = result.etag
            page.content_hash = result.content_hash
            page.title = result.title
            if result.status is None or not 200 <= result.status < 300:
                if result.status in {404, 410}:
                    observation.currently_live = False
                    removed += 1
                continue
            if result.matched_link is None:
                observation.currently_live = False
                removed += 1
                continue
            link = result.matched_link
            observation.anchor_text = link.anchor
            observation.context_text = link.context
            observation.semantic_location = link.semantic_location
            observation.rel_flags = list(link.rel_flags)
            observation.is_editorial = link.editorial
            observation.is_sitewide = link.semantic_location in {"nav", "footer", "header"}
            observation.currently_live = True
            observation.last_seen = now
            live += 1

    return {
        "checked": len(results),
        "live": live,
        "removed": removed,
        "unchanged": unchanged,
        "robots_blocked": blocked,
        "errors": errors,
    }
