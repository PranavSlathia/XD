from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from dh.sources.marketplace.dropcatch import (
    DropCatchSourceError,
    fetch_domain_detail,
    fetch_pending_delete_feed,
)
from dh.sources.namebio.retail_stats import (
    MarketEvidence,
    PlacementStats,
    RetailKeywordStats,
    find_market_evidence,
)
from dh.sources.openpagerank.top_domains import (
    TopDomainRecord,
    ensure_top_domains_dataset,
    intersect_top_domains,
)
from dh.workers.inventory import _prioritize_detail_records


def _zip_bytes(filename: str, body: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, body)
    return output.getvalue()


def _keyword(
    value: str,
    *,
    start: PlacementStats | None = None,
    end: PlacementStats | None = None,
) -> RetailKeywordStats:
    zero = PlacementStats(sale_count=0, price_sum=0, price_avg=0, price_max=0)
    return RetailKeywordStats(
        keyword=value,
        placements={
            "exact": zero,
            "start": start or zero,
            "end": end or zero,
            "middle": zero,
        },
    )


@pytest.mark.anyio
async def test_dropcatch_feed_is_read_only_and_prefiltered() -> None:
    archive = _zip_bytes(
        "Dropping_AllDays_2026-08-20.csv",
        "Domain,TLD,Type,Drop Date\n"
        "usefulname.com,com,Pending Delete,2026-08-23\n"
        "with-hyphen.com,com,Pending Delete,2026-08-23\n"
        "tiny.com,com,Pending Delete,2026-08-23\n"
        "different.net,net,Pending Delete,2026-08-23\n",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "client.dropcatch.com":
            assert request.method == "GET"
            assert request.url.path == "/GetFileUrl"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {"fileUrl": "https://dropcatch-downloads.s3.amazonaws.com/feed.zip"},
                },
            )
        return httpx.Response(200, content=archive)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        feed = await fetch_pending_delete_feed(
            allowed_tlds=("com",), min_sld_length=5, max_sld_length=18, client=client
        )

    assert feed.fetched_count == 4
    assert [row.domain for row in feed.listings] == ["usefulname.com"]
    assert feed.listings[0].external_key == "usefulname.com:2026-08-23:pending-delete"
    assert feed.listings[0].listing_url.endswith("/usefulname.com")


@pytest.mark.anyio
async def test_dropcatch_rejects_untrusted_download_host() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {"fileUrl": "https://attacker.example/feed.zip"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DropCatchSourceError, match="untrusted"):
            await fetch_pending_delete_feed(client=client)


@pytest.mark.anyio
async def test_dropcatch_detail_parses_price_and_deadline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/GetDomainDetail"
        assert request.url.params["DomainName"] == "meowfarm.com"
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "item": {
                        "id": 123,
                        "recordType": "Pending Delete",
                        "expirationDate": "2026-08-20T18:00:00Z",
                        "nextValidBid": 59,
                        "highBid": "75.50",
                        "bidCount": 2,
                    }
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        detail = await fetch_domain_detail("meowfarm.com", client=client)

    assert detail.external_id == "123"
    assert detail.minimum_price_micros == 59_000_000
    assert detail.current_price_micros == 75_500_000
    assert detail.closes_at is not None
    assert detail.closes_at.isoformat() == "2026-08-20T18:00:00+00:00"


@pytest.mark.anyio
async def test_openpagerank_reference_download_cache_and_intersection(tmp_path: Path) -> None:
    archive = _zip_bytes(
        "top10milliondomains.csv",
        "Rank,Domain,Extension,Open Page Rank,Referring Domains\n"
        "1,irrelevant.com,com,7.00,9000\n"
        "2,alpha.com,com,4.20,120\n"
        "3,beta.com,com,3.10,9\n"
        "4,gamma.com,com,2.90,45\n"
        "5,below.com,com,2.40,1000\n",
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=archive,
            headers={"Last-Modified": "Thu, 30 Jul 2026 00:00:00 GMT"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        dataset = await ensure_top_domains_dataset(tmp_path, client=client)
        cached = await ensure_top_domains_dataset(tmp_path, client=client)

    assert calls == 1
    assert dataset.refreshed is True
    assert cached.refreshed is False
    matches = intersect_top_domains(
        dataset.path,
        {"alpha.com", "beta.com", "gamma.com", "below.com"},
        min_open_pagerank=2.5,
        min_referring_domains=10,
        limit=10,
    )
    assert [(row.domain, row.rank) for row in matches] == [
        ("alpha.com", 2),
        ("gamma.com", 4),
    ]


def test_namebio_stats_segment_compound_and_preserve_attribution_evidence() -> None:
    known = {
        "finance": _keyword(
            "finance",
            start=PlacementStats(
                sale_count=81, price_sum=197_803, price_avg=2442.01, price_max=11_131
            ),
        ),
        "brokerage": _keyword(
            "brokerage",
            end=PlacementStats(sale_count=10, price_sum=11_706, price_avg=1170.60, price_max=2_500),
        ),
    }
    evidence = find_market_evidence("financebrokerage.com", known)
    assert evidence is not None
    assert evidence.terms == ("finance", "brokerage")
    assert evidence.sale_count_floor == 10
    assert evidence.price_avg_floor == pytest.approx(1170.6, abs=0.1)


def test_detail_budget_prioritizes_demand_over_raw_authority_rank() -> None:
    records = [
        TopDomainRecord("plateau.com", 10, 7.2, 7_000),
        TopDomainRecord("genericname.com", 20, 4.0, 200),
        TopDomainRecord("floornut.com", 1_000, 2.86, 82),
    ]
    market = MarketEvidence(
        terms=("floor", "nut"),
        sale_count_floor=10,
        price_avg_floor=2678.0,
        price_max=12_000,
        placements=(),
    )

    prioritized = _prioritize_detail_records(
        records,
        market_by_domain={"floornut.com": market},
        authority_cohort_sizes={"plateau.com": 12},
    )

    assert [row.domain for row in prioritized] == [
        "floornut.com",
        "genericname.com",
        "plateau.com",
    ]
