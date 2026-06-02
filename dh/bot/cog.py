"""The /dh command group, decision buttons, and the daily-digest task."""

from __future__ import annotations

import datetime as dt
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from dh.bot import embeds, queries
from dh.config import settings
from dh.logging import log


def _is_owner(interaction: discord.Interaction) -> bool:
    return settings.discord_owner_id == 0 or interaction.user.id == settings.discord_owner_id


class DecisionView(discord.ui.View):
    """Bought / Pass / Watching buttons for one candidate."""

    def __init__(self, domain: str) -> None:
        super().__init__(timeout=None)
        self.domain = domain

    async def _decide(self, interaction: discord.Interaction, decision: str) -> None:
        if not _is_owner(interaction):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        try:
            ok = await queries.record_outcome(self.domain, decision)
        except Exception as e:  # surface any failure to the operator, don't crash the view
            log.error("dhbot.decision.error", domain=self.domain, error=str(e))
            await interaction.response.send_message(f"Failed to record: {e}", ephemeral=True)
            return
        if not ok:
            await interaction.response.send_message(f"`{self.domain}` not found.", ephemeral=True)
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(
            content=f"✅ **{self.domain}** → {decision}", view=self
        )

    @discord.ui.button(label="Bought", style=discord.ButtonStyle.success, emoji="💰")
    async def bought(
        self, interaction: discord.Interaction, _button: discord.ui.Button[Any]
    ) -> None:
        await self._decide(interaction, "bought")

    @discord.ui.button(label="Watching", style=discord.ButtonStyle.primary, emoji="👀")
    async def watching(
        self, interaction: discord.Interaction, _button: discord.ui.Button[Any]
    ) -> None:
        await self._decide(interaction, "watching")

    @discord.ui.button(label="Pass", style=discord.ButtonStyle.secondary, emoji="🚫")
    async def passed(
        self, interaction: discord.Interaction, _button: discord.ui.Button[Any]
    ) -> None:
        await self._decide(interaction, "passed")


class DHCog(commands.GroupCog, name="dh"):
    """Domain Hunter — browse the shortlist + record decisions from Discord."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__()
        digest_time = dt.time(
            hour=settings.discord_digest_hour_utc,
            minute=settings.discord_digest_minute_utc,
            tzinfo=dt.UTC,
        )
        self.daily_digest.change_interval(time=digest_time)
        self.daily_digest.start()

    async def cog_unload(self) -> None:
        self.daily_digest.cancel()

    async def _post_shortlist(self, send: Any, *, header: str) -> int:
        items = await queries.fetch_shortlist()
        if not items:
            await send(content=f"{header}\n_Nothing on the shortlist right now._")
            return 0
        await send(content=header)
        for item in items:
            await send(embed=embeds.shortlist_item_embed(item), view=DecisionView(item.domain))
        return len(items)

    @app_commands.command(
        name="shortlist", description="Today's ranked domain shortlist with decision buttons."
    )
    async def shortlist(self, interaction: discord.Interaction) -> None:
        if not _is_owner(interaction):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        await self._post_shortlist(
            interaction.followup.send, header="**🦅 Vulture — today's carcasses**"
        )

    @app_commands.command(
        name="candidates", description="Browse candidates (filter by score / status)."
    )
    @app_commands.describe(
        min_score="minimum composite score", status="availability status", limit="rows (max 25)"
    )
    async def candidates(
        self,
        interaction: discord.Interaction,
        min_score: float | None = None,
        status: str | None = None,
        limit: app_commands.Range[int, 1, 25] = 15,
    ) -> None:
        if not _is_owner(interaction):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        rows = await queries.fetch_candidates(min_score=min_score, status=status, limit=limit + 1)
        has_more = len(rows) > limit
        await interaction.followup.send(
            embed=embeds.candidates_list_embed(rows[:limit], 0, has_more)
        )

    @app_commands.command(name="domain", description="Full detail + evidence for one candidate.")
    @app_commands.describe(name="candidate domain")
    async def domain(self, interaction: discord.Interaction, name: str) -> None:
        if not _is_owner(interaction):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        detail = await queries.fetch_candidate_detail(name.strip().lower())
        if detail is None:
            await interaction.followup.send(f"`{name}` not found.")
            return
        await interaction.followup.send(
            embed=embeds.candidate_detail_embed(detail), view=DecisionView(detail.candidate.domain)
        )

    @domain.autocomplete("name")
    async def _domain_ac(
        self, _interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            names = await queries.candidate_domains(current.strip().lower(), limit=20)
        except Exception:  # autocomplete must never raise
            return []
        return [app_commands.Choice(name=n, value=n) for n in names[:20]]

    @app_commands.command(name="config", description="Current scoring weights + thresholds.")
    async def config(self, interaction: discord.Interaction) -> None:
        if not _is_owner(interaction):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        cfg = await queries.current_config()
        await interaction.followup.send(embed=embeds.config_embed(cfg))

    @tasks.loop(time=dt.time(hour=3, minute=30, tzinfo=dt.UTC))
    async def daily_digest(self) -> None:
        if settings.discord_channel_id == 0:
            return
        channel = self.bot.get_channel(settings.discord_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            log.warning("dhbot.digest.no_channel", channel_id=settings.discord_channel_id)
            return
        try:
            n = await self._post_shortlist(
                channel.send, header="**🦅 Vulture's daily drop — freshest carcasses**"
            )
            log.info("dhbot.digest.posted", count=n)
        except Exception as e:  # a digest failure must not kill the loop
            log.error("dhbot.digest.error", error=str(e))

    @daily_digest.before_loop
    async def _before_digest(self) -> None:
        await self.bot.wait_until_ready()
