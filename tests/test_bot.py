"""Unit tests for the dh-bot pure layer (embeds + helpers). No DB, no gateway."""

from __future__ import annotations

import pytest

from dh.bot import embeds, queries


def test_fmt_price_and_score() -> None:
    assert embeds.fmt_price(11_060_000) == "$11.06"
    assert embeds.fmt_price(None) == "—"
    assert embeds.fmt_score(57.4) == "57.4"
    assert embeds.fmt_score(None) == "—"


def test_shortlist_item_embed() -> None:
    item = queries.ShortlistItem(
        domain="example.com",
        composite_score=58.2,
        current_status="available",
        quote_price_micros=11_060_000,
        top_reasons=["authoritative availability: +100", "Open PageRank authority: +45"],
    )
    e = embeds.shortlist_item_embed(item)
    assert e.title == "example.com"
    assert e.description is not None and "58.2" in e.description and "$11.06" in e.description
    assert any(f.name == "Why" for f in e.fields)


def test_candidate_detail_embed_hard_filtered() -> None:
    detail = queries.CandidateDetail(
        candidate=queries.CandidateRow(
            domain="dead.com",
            composite_score=0.0,
            current_status="available",
            availability_confidence="authoritative",
            open_pagerank=1.08,
            hard_filtered=True,
            hard_filter_reason="low_authority",
            top_reasons=[],
        ),
        mentions=[
            queries.MentionRow(
                source_url="https://github.com/x/y", context_type="prose", context_snippet=None
            )
        ],
        availability=[
            queries.AvailabilityRow(source="rdap", status="available", is_authoritative=True)
        ],
        wayback=[
            queries.WaybackRow(
                first_capture="2010-01-01", last_capture="2021-06-01", capture_count=42
            )
        ],
        latest_quote_micros=None,
        latest_decision="watching",
    )
    e = embeds.candidate_detail_embed(detail)
    assert e.title == "dead.com"
    assert any(f.name is not None and "Hard-filtered" in f.name for f in e.fields)
    assert any(f.name == "Availability" for f in e.fields)
    assert e.footer.text is not None and "watching" in e.footer.text


def test_candidates_list_embed_empty_and_rows() -> None:
    assert "No candidates" in (embeds.candidates_list_embed([], 0, False).description or "")
    rows = [
        queries.CandidateRow("a.com", 60.0, "available", "authoritative", 4.0, False, None, []),
        queries.CandidateRow("b.com", 10.0, "registered", None, None, True, "not_available", []),
    ]
    e = embeds.candidates_list_embed(rows, 0, True)
    assert e.description is not None and "a.com" in e.description and "b.com" in e.description
    assert e.footer.text == "more →"


def test_config_embed() -> None:
    cfg = queries.ConfigInfo(
        weights_version=3,
        weights={"open_pagerank_score": 0.45, "availability_score": 0.15},
        digest_min_score=40,
        digest_max_items=10,
        premium_ceiling_usd=200,
        opr_min_authority=3.0,
    )
    e = embeds.config_embed(cfg)
    assert e.description is not None and "v3" in e.description
    assert any(f.name == "Weights" for f in e.fields)


@pytest.mark.anyio
async def test_record_outcome_rejects_unknown_decision() -> None:
    with pytest.raises(ValueError, match="invalid decision"):
        await queries.record_outcome("example.com", "nuke")
