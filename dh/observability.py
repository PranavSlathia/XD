"""Sentry / GlitchTip integration shim.

``setup_sentry()`` is called from each entry point. No-op if DH_SENTRY_DSN
is unset, so dev / tests pay no cost.
"""
from __future__ import annotations

from dh.config import settings
from dh.logging import log


def setup_sentry(*, service: str) -> None:
    if not settings.sentry_dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            traces_sample_rate=0.0,
            send_default_pii=False,
            environment=settings.env,
            release=f"dh-{service}",
        )
        log.info("sentry.enabled", service=service)
    except Exception as e:
        log.warning("sentry.init.failed", error=str(e))
