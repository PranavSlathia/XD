from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import urllib.robotparser
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import tldextract
from sqlalchemy import select

from dh.db.engine import session_scope
from dh.db.models import Candidate, CrawlRun, CrawlSeed, LinkObservation, SourcePage
from dh.engine.assessments import assess_candidate
from dh.engine.configuration import get_active_config
from dh.sources.content.parser import ExtractedLink, parse_html, parse_pdf_urls
from dh.sources.content.security import Resolver, resolve_public_url, system_resolver

USER_AGENT = "XD-Domain-Hunter/1.0 (+private research crawler)"
_extract = tldextract.TLDExtract(suffix_list_urls=())


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    status: int
    content_type: str
    content: bytes
    etag: str | None


@dataclass(frozen=True, slots=True)
class CachedPage:
    etag: str | None
    outgoing_urls: tuple[str, ...]


async def _fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    resolver: Resolver,
    max_bytes: int,
    timeout_seconds: float,
    max_redirects: int = 5,
    etag: str | None = None,
) -> FetchedPage:
    current = url
    conditional_etag = etag
    for _ in range(max_redirects + 1):
        current = await resolve_public_url(current, resolver=resolver)
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf"}
        if conditional_etag:
            headers["If-None-Match"] = conditional_etag
        async with client.stream(
            "GET",
            current,
            headers=headers,
            timeout=timeout_seconds,
            follow_redirects=False,
        ) as response:
            if response.status_code == 304:
                return FetchedPage(
                    url=str(response.url),
                    status=304,
                    content_type=response.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .lower(),
                    content=b"",
                    etag=response.headers.get("etag") or etag,
                )
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise RuntimeError("redirect response had no location")
                current = str(response.url.join(location))
                conditional_etag = None
                continue
            length = response.headers.get("content-length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise RuntimeError("response exceeded configured byte limit")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise RuntimeError("response exceeded configured byte limit")
            return FetchedPage(
                url=str(response.url),
                status=response.status_code,
                content_type=response.headers.get("content-type", "").split(";", 1)[0].lower(),
                content=bytes(body),
                etag=response.headers.get("etag"),
            )
    raise RuntimeError("redirect limit exceeded")


async def _cached_page(url: str) -> CachedPage:
    async with session_scope() as session:
        source = (
            await session.execute(select(SourcePage).where(SourcePage.url == url))
        ).scalar_one_or_none()
        if source is None:
            return CachedPage(etag=None, outgoing_urls=())
        return CachedPage(
            etag=source.etag,
            outgoing_urls=tuple(source.outgoing_urls or ()),
        )


async def _touch_cached_page(url: str) -> tuple[str, ...]:
    now = dt.datetime.now(dt.UTC)
    async with session_scope() as session:
        source = (
            await session.execute(select(SourcePage).where(SourcePage.url == url))
        ).scalar_one_or_none()
        if source is None:
            return ()
        source.last_seen = now
        observations = (
            (
                await session.execute(
                    select(LinkObservation).where(
                        LinkObservation.source_page_id == source.id
                    )
                )
            )
            .scalars()
            .all()
        )
        for observation in observations:
            observation.last_seen = now
            observation.currently_live = True
        return tuple(source.outgoing_urls or ())


async def _robots_allows(
    client: httpx.AsyncClient,
    url: str,
    *,
    resolver: Resolver,
    max_bytes: int,
    timeout_seconds: float,
) -> bool:
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        page = await _fetch(
            client,
            robots_url,
            resolver=resolver,
            max_bytes=min(max_bytes, 512_000),
            timeout_seconds=timeout_seconds,
        )
    except (httpx.HTTPError, RuntimeError, ValueError):
        return False
    if page.status == 404:
        return True
    if not 200 <= page.status < 300:
        return False
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(page.content.decode("utf-8", errors="replace").splitlines())
    return parser.can_fetch(USER_AGENT, url)


def _registrable_domain(url: str) -> str | None:
    host = urlsplit(url).hostname
    if not host:
        return None
    result = _extract(host)
    if not result.domain or not result.suffix:
        return None
    return f"{result.domain}.{result.suffix}".lower()


def prioritized_external_domains(
    links: tuple[ExtractedLink, ...],
    *,
    source_url: str,
    core_tlds: tuple[str, ...],
    limit: int,
) -> tuple[str, ...]:
    """Select bounded core-TLD targets, preferring editorial follow links."""

    core_suffixes = {f".{item}" for item in core_tlds}
    source_domain = _registrable_domain(source_url)
    domain_priority: dict[str, int] = {}
    for item in links:
        domain = _registrable_domain(item.url)
        if domain is None or domain == source_domain or not any(
            domain.endswith(suffix) for suffix in core_suffixes
        ):
            continue
        priority = 2 if item.editorial and "nofollow" not in item.rel_flags else 1
        domain_priority[domain] = max(domain_priority.get(domain, 0), priority)
    return tuple(
        sorted(
            domain_priority,
            key=lambda domain: (-domain_priority[domain], domain),
        )[:limit]
    )


async def _persist_page(
    *,
    seed: CrawlSeed,
    fetched: FetchedPage,
    title: str | None,
    links: tuple[ExtractedLink, ...],
    core_tlds: tuple[str, ...],
    max_external_domains: int,
) -> int:
    now = dt.datetime.now(dt.UTC)
    async with session_scope() as session:
        source = (
            await session.execute(select(SourcePage).where(SourcePage.url == fetched.url))
        ).scalar_one_or_none()
        if source is None:
            source = SourcePage(
                seed_id=seed.id,
                url=fetched.url,
                host=urlsplit(fetched.url).hostname or seed.allowed_host,
                source_kind=seed.source_kind,
                first_seen=now,
            )
            session.add(source)
            await session.flush()
        source.last_seen = now
        source.http_status = fetched.status
        source.content_type = fetched.content_type
        source.etag = fetched.etag
        source.content_hash = hashlib.sha256(fetched.content).digest()
        source.title = title
        source.outgoing_urls = sorted(
            {
                item.url
                for item in links
                if urlsplit(item.url).hostname == seed.allowed_host
            }
        )[:500]

        domains = prioritized_external_domains(
            links,
            source_url=fetched.url,
            core_tlds=core_tlds,
            limit=max_external_domains,
        )
        candidate_rows = list(
            (
                await session.execute(
                    select(Candidate).where(Candidate.domain.in_(domains))
                )
            )
            .scalars()
            .all()
        )
        candidates_by_domain = {row.domain: row for row in candidate_rows}
        for domain in domains:
            if domain in candidates_by_domain:
                candidates_by_domain[domain].last_observed = now
                continue
            candidate = Candidate(
                domain=domain,
                first_observed=now,
                last_observed=now,
                lifecycle_state="observed",
                review_state="research",
            )
            session.add(candidate)
            candidate_rows.append(candidate)
            candidates_by_domain[domain] = candidate
        await session.flush()
        candidates = {domain: row.id for domain, row in candidates_by_domain.items()}
        existing = (
            (
                await session.execute(
                    select(LinkObservation).where(LinkObservation.source_page_id == source.id)
                )
            )
            .scalars()
            .all()
        )
        # A successful re-fetch is a fresh snapshot. Links not present in the
        # new document must stop counting as currently live.
        for observation in existing:
            observation.currently_live = False
        by_hash = {row.target_url_hash: row for row in existing}
        persisted = 0
        for item in links:
            target_domain = _registrable_domain(item.url)
            if target_domain is None or target_domain == _registrable_domain(fetched.url):
                continue
            digest = hashlib.sha256(item.url.encode("utf-8")).digest()
            observation = by_hash.get(digest)
            if observation is None:
                observation = LinkObservation(
                    source_page_id=source.id,
                    target_url=item.url,
                    target_url_hash=digest,
                    target_domain=target_domain,
                    first_seen=now,
                )
                session.add(observation)
                by_hash[digest] = observation
                persisted += 1
            if candidate_id := candidates.get(target_domain):
                observation.candidate_id = candidate_id
            observation.anchor_text = item.anchor
            observation.context_text = item.context
            observation.semantic_location = item.semantic_location
            observation.rel_flags = list(item.rel_flags)
            observation.is_editorial = item.editorial
            observation.is_sitewide = item.semantic_location in {"nav", "footer", "header"}
            observation.currently_live = True
            observation.last_seen = now
        await session.flush()
        for candidate in candidate_rows:
            await assess_candidate(session, candidate)
        return persisted


async def run_seed(
    seed_id: int,
    *,
    operator_job_id: str | None = None,
    resolver: Resolver = system_resolver,
) -> dict[str, int]:
    async with session_scope() as session:
        seed = await session.get(CrawlSeed, seed_id)
        if seed is None or not seed.enabled:
            raise ValueError("crawl seed is missing or disabled")
        if seed.terms_verified_at is None:
            raise ValueError("crawl seed terms have not been verified")
        _config_row, config = await get_active_config(session)
        run = CrawlRun(seed_id=seed.id, operator_job_id=operator_job_id, status="running")
        session.add(run)
        await session.flush()
        run_id = run.id
        seed_snapshot = CrawlSeed(
            id=seed.id,
            url=seed.url,
            source_kind=seed.source_kind,
            allowed_host=seed.allowed_host,
            enabled=seed.enabled,
            terms_verified_at=seed.terms_verified_at,
            max_pages=seed.max_pages,
        )

    max_pages = min(seed_snapshot.max_pages, config.crawler.max_pages_per_seed)
    queue: deque[str] = deque([seed_snapshot.url])
    seen: set[str] = set()
    pages_fetched = links_observed = 0
    error: str | None = None
    async with httpx.AsyncClient(http2=True) as client:
        while queue and pages_fetched < max_pages:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            try:
                normalized = await resolve_public_url(url, resolver=resolver)
                if urlsplit(normalized).hostname != seed_snapshot.allowed_host:
                    continue
                if not await _robots_allows(
                    client,
                    normalized,
                    resolver=resolver,
                    max_bytes=config.crawler.max_response_bytes,
                    timeout_seconds=config.crawler.request_timeout_seconds,
                ):
                    continue
                cached = await _cached_page(normalized)
                fetched = await _fetch(
                    client,
                    normalized,
                    resolver=resolver,
                    max_bytes=config.crawler.max_response_bytes,
                    timeout_seconds=config.crawler.request_timeout_seconds,
                    etag=cached.etag,
                )
                if fetched.status == 304:
                    outgoing = await _touch_cached_page(fetched.url)
                    pages_fetched += 1
                    for next_url in outgoing or cached.outgoing_urls:
                        if (
                            urlsplit(next_url).hostname == seed_snapshot.allowed_host
                            and next_url not in seen
                        ):
                            queue.append(next_url)
                    await asyncio.sleep(config.crawler.minimum_delay_seconds)
                    continue
                if not 200 <= fetched.status < 300:
                    raise RuntimeError(f"source page returned HTTP {fetched.status}")
                if fetched.content_type == "text/html":
                    title, links = parse_html(fetched.content, fetched.url)
                elif fetched.content_type == "application/pdf":
                    title, links = None, parse_pdf_urls(fetched.content)
                else:
                    continue
                links_observed += await _persist_page(
                    seed=seed_snapshot,
                    fetched=fetched,
                    title=title,
                    links=links,
                    core_tlds=config.core_tlds,
                    max_external_domains=config.crawler.max_external_domains_per_page,
                )
                pages_fetched += 1
                for item in links:
                    if urlsplit(item.url).hostname == seed_snapshot.allowed_host and item.url not in seen:
                        queue.append(item.url)
                await asyncio.sleep(config.crawler.minimum_delay_seconds)
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                error = f"{type(exc).__name__}: {exc}"[:1000]
                continue

    async with session_scope() as session:
        run = await session.get(CrawlRun, run_id)
        if run is not None:
            run.status = "partial" if error else "success"
            run.finished_at = dt.datetime.now(dt.UTC)
            run.pages_fetched = pages_fetched
            run.links_observed = links_observed
            run.error = error
            run.metrics = {"urls_seen": len(seen), "max_pages": max_pages}
    return {"pages_fetched": pages_fetched, "links_observed": links_observed}
