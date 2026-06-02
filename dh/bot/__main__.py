"""dh-bot entrypoint: ``python -m dh.bot``.

A discord.py bot exposing the /dh command group. Slash-only (no privileged intents).
Syncs commands to the configured guild on startup for instant availability.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from dh.bot.cog import DHCog
from dh.config import settings
from dh.logging import configure_logging, log
from dh.observability import setup_sentry


class DHBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()  # guilds only; no message-content needed for slash
        activity = discord.Activity(
            type=discord.ActivityType.watching, name="the web's dead domains 🦅"
        )
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            activity=activity,
        )

    async def setup_hook(self) -> None:
        await self.add_cog(DHCog(self))
        if settings.discord_guild_id:
            guild = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("dhbot.commands.synced", guild=settings.discord_guild_id, count=len(synced))

    async def on_ready(self) -> None:
        log.info("dhbot.ready", user=str(self.user))


def main() -> None:
    configure_logging()
    if not settings.discord_bot_token:
        log.error("dhbot.no_token", hint="set DH_DISCORD_BOT_TOKEN in .env")
        raise SystemExit(1)
    setup_sentry(service="bot")
    DHBot().run(settings.discord_bot_token, log_handler=None)


if __name__ == "__main__":
    main()
