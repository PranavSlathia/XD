"""Discord webhook helper.

`discord_smoke()` is exposed as `dh discord smoke` — a manual command that
posts a single test message. **Disabled** if DH_DISCORD_WEBHOOK_URL is empty;
that's how we keep the command safe in scaffold-mode (no creds yet).
"""
from __future__ import annotations

from typing import Any

import httpx

from dh.api.schemas import CandidateDigestItem
from dh.config import settings


class DiscordWebhookNotConfigured(RuntimeError):
    """Raised when DH_DISCORD_WEBHOOK_URL is empty/missing."""


def build_digest_payload(candidates: list[CandidateDigestItem]) -> dict[str, Any]:
    """Render a Discord webhook payload from digest candidates.

    Pure — no IO. Lets us unit-test the embed shape.
    """
    if not candidates:
        embeds: list[dict[str, Any]] = [
            {
                "title": "Today's digest is empty",
                "description": "No candidates met the digest gate today.",
                "color": 0x9E9E9E,
            }
        ]
    else:
        embeds = []
        for c in candidates[:10]:
            price = ""
            if c.quote_price_micros:
                price = f" · ~${c.quote_price_micros / 1_000_000:.0f}"
            embeds.append(
                {
                    "title": c.domain,
                    "description": (
                        f"score: {c.composite_score:.1f}" if c.composite_score is not None
                        else "score: n/a"
                    ) + f" · status: {c.current_status or 'unknown'}{price}",
                    "color": 0x4CAF50,
                    "fields": [
                        {"name": "Reasons", "value": ", ".join(c.top_reasons) or "—", "inline": False}
                    ],
                }
            )
    return {"username": "Domain Hunter", "embeds": embeds}


async def post_digest(candidates: list[CandidateDigestItem]) -> bool:
    """Post the daily digest. Returns True if sent, False if skipped/unconfigured."""
    url = settings.discord_webhook_url
    if not url:
        return False
    payload = build_digest_payload(candidates)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    return True


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
