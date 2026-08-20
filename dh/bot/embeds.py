"""Pure Discord embed builders. No DB, no gateway — unit-testable."""

from __future__ import annotations

import discord

from dh.bot.queries import CandidateDetail, CandidateRow, ConfigInfo, ShortlistItem

_OK = discord.Color.green()
_WARN = discord.Color.orange()
_MUTED = discord.Color.light_grey()


def fmt_price(micros: int | None) -> str:
    if micros is None:
        return "—"
    return f"${micros / 1_000_000:,.2f}"


def fmt_score(score: float | None) -> str:
    return f"{score:.1f}" if score is not None else "—"


def _opr(opr: float | None) -> str:
    return f"{opr:.2f}" if opr is not None else "—"


def shortlist_item_embed(item: ShortlistItem) -> discord.Embed:
    """One research card. Any acquisition remains an explicit human action."""
    embed = discord.Embed(
        title=item.domain,
        description=(
            f"**research score** {fmt_score(item.composite_score)} · "
            f"**status** {item.current_status or 'unknown'} · "
            f"**price** {fmt_price(item.quote_price_micros)}"
        ),
        color=_WARN,
    )
    if item.top_reasons:
        embed.add_field(
            name="Why", value="\n".join(f"• {r}" for r in item.top_reasons[:6]), inline=False
        )
    if item.closes_at:
        embed.add_field(name="Deadline", value=item.closes_at, inline=False)
    if item.missing_evidence:
        embed.add_field(
            name="Required before acquisition",
            value="\n".join(f"• {value}" for value in item.missing_evidence[:6]),
            inline=False,
        )
    embed.set_footer(text="Research only · no bid or purchase is placed by Domain Hunter")
    return embed


def candidate_detail_embed(detail: CandidateDetail) -> discord.Embed:
    c: CandidateRow = detail.candidate
    color = _MUTED if c.hard_filtered else _OK
    embed = discord.Embed(
        title=c.domain,
        description=(
            f"**score** {fmt_score(c.composite_score)} · **status** {c.current_status or 'unknown'} "
            f"({c.availability_confidence or 'no confidence'}) · **OPR** {_opr(c.open_pagerank)} · "
            f"**price** {fmt_price(detail.latest_quote_micros)}"
        ),
        color=color,
    )
    if c.hard_filtered:
        embed.add_field(
            name="⛔ Hard-filtered", value=c.hard_filter_reason or "(reason unset)", inline=False
        )
    if c.top_reasons:
        embed.add_field(
            name="Why", value="\n".join(f"• {r}" for r in c.top_reasons[:6]), inline=False
        )
    if detail.availability:
        embed.add_field(
            name="Availability",
            value="\n".join(
                f"• {a.source}: {a.status or '?'}{' (authoritative)' if a.is_authoritative else ''}"
                for a in detail.availability[:4]
            ),
            inline=False,
        )
    if detail.wayback:
        w = detail.wayback[0]
        embed.add_field(
            name="Wayback",
            value=f"{w.first_capture or '?'} → {w.last_capture or '?'} ({w.capture_count or 0} captures)",
            inline=False,
        )
    if detail.mentions:
        embed.add_field(
            name=f"Cited in ({len(detail.mentions)})",
            value="\n".join(
                f"• {m.source_url or '?'} [{m.context_type or '?'}]" for m in detail.mentions[:5]
            )[:1000],
            inline=False,
        )
    if detail.latest_decision:
        embed.set_footer(text=f"last decision: {detail.latest_decision}")
    return embed


def candidates_list_embed(rows: list[CandidateRow], page: int, has_more: bool) -> discord.Embed:
    if not rows:
        return discord.Embed(title="Candidates", description="No candidates match.", color=_MUTED)
    lines = [
        f"`{fmt_score(r.composite_score):>5}` **{r.domain}** — {r.current_status or 'unknown'}"
        + (f" ⛔ {r.hard_filter_reason}" if r.hard_filtered else "")
        for r in rows
    ]
    embed = discord.Embed(
        title=f"Candidates · page {page + 1}", description="\n".join(lines)[:4000], color=_OK
    )
    embed.set_footer(text="more →" if has_more else "end")
    return embed


def config_embed(cfg: ConfigInfo) -> discord.Embed:
    embed = discord.Embed(
        title="Scoring config",
        description=(
            f"weights **v{cfg.weights_version}** · digest min score **{cfg.digest_min_score}** · "
            f"max items **{cfg.digest_max_items}** · premium ceiling **${cfg.premium_ceiling_usd}** · "
            f"OPR floor **{cfg.opr_min_authority}**"
        ),
        color=_WARN,
    )
    if cfg.weights:
        embed.add_field(
            name="Weights",
            value="\n".join(f"`{k}` {v}" for k, v in sorted(cfg.weights.items()))[:1000],
            inline=False,
        )
    return embed
