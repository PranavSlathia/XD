from __future__ import annotations

import logging

from dh.logging import configure_logging


def test_http_transport_info_logs_are_suppressed() -> None:
    configure_logging()

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
