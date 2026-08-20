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


async def _fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    resolver: Resolver,
    max_bytes: int,
    timeout_seconds: float,
    max_redirects: int = 5,
) -> FetchedPage:
    current = url
    for _ in range(max_redirects + 1):
        current = await resolve_public_url(current, resolver=resolver)
        async with client.stream(
            "GET",
            current,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf"},
            timeout=timeout_seconds,
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise RuntimeError("redirect response had no location")
                current = str(response.url.join(location))
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


async def _persist_page(
    *,
    seed: CrawlSeed,
    fetched: FetchedPage,
    title: str | None,
    links: tuple[ExtractedLink, ...],
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

        domains = sorted(
            {
                domain
                for item in links
                if (domain := _registrable_domain(item.url)) is not None
            }
        )
        candidate_rows: list[Candidate] = []
        if domains:
            candidate_rows = list(
                (
                    await session.execute(
                        select(Candidate).where(Candidate.domain.in_(domains))
                    )
                )
                .scalars()
                .all()
            )
        candidates = {row.domain: row.id for row in candidate_rows}
        existing = (
            (
                await session.execute(
                    select(LinkObservation).where(LinkObservation.source_page_id == source.id)
                )
            )
            .scalars()
            .all()
        )
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
            observation.candidate_id = candidates.get(target_domain)
            observation.anchor_text = item.anchor
            observation.context_text = item.context
            observation.semantic_location = item.semantic_location
            observation.rel_flags = list(item.rel_flags)
            observation.is_editorial = item.editorial
            observation.is_sitewide = item.semantic_location in {"nav", "footer", "header"}
            observation.currently_live = True
            observation.last_seen = now
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
                fetched = await _fetch(
                    client,
                    normalized,
                    resolver=resolver,
                    max_bytes=config.crawler.max_response_bytes,
                    timeout_seconds=config.crawler.request_timeout_seconds,
                )
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
