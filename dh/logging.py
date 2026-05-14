"""Structured JSON logging via structlog."""
from __future__ import annotations

import logging
import sys

import structlog
from structlog.types import EventDict

from dh.config import settings


def _drop_color_keys(_: object, __: str, event_dict: EventDict) -> EventDict:
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging() -> None:
    """Idempotent. Call once at process startup."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )

    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _drop_color_keys,
    ]

    if settings.env == "dev":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


log = structlog.get_logger("dh")
