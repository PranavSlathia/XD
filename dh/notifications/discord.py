"""Discord webhook helper.

`discord_smoke()` is exposed as `dh discord smoke` — a manual command that
posts a single test message. **Disabled** if DH_DISCORD_WEBHOOK_URL is empty;
that's how we keep the command safe in scaffold-mode (no creds yet).
"""
from __future__ import annotations

import httpx

from dh.config import settings


class DiscordWebhookNotConfigured(RuntimeError):
    """Raised when DH_DISCORD_WEBHOOK_URL is empty/missing."""


async def discord_smoke() -> None:
    """Post a smoke-test embed to the configured Discord webhook.

    Raises DiscordWebhookNotConfigured if no webhook is set.
    """
    url = settings.discord_webhook_url
    if not url:
        raise DiscordWebhookNotConfigured(
            "DH_DISCORD_WEBHOOK_URL is empty. Set it in .env to enable Discord notifications. "
            "Until then, this command is a no-op."
        )

    payload = {
        "username": "Domain Hunter",
        "embeds": [
            {
                "title": "Smoke test",
                "description": "If you can read this, the Discord webhook works.",
                "color": 0x4CAF50,
            }
        ],
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
