"""The bot token must never reach the logs.

Regression guard for a real leak: the Telegram Bot API embeds the token in the
URL path (``/bot<TOKEN>/sendMessage``), and httpx logs full request URLs at INFO,
so the token was being written to our logs on every outbound message.
"""

from __future__ import annotations

import logging

from synapse.observability.logging import configure_logging


def test_http_loggers_cannot_emit_urls_at_info() -> None:
    configure_logging(level="INFO", json_output=True)
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        # INFO carries the credential-bearing URL; it must be suppressed.
        assert not logger.isEnabledFor(logging.INFO), f"{name} would log request URLs"
        # Genuine failures must still surface.
        assert logger.isEnabledFor(logging.WARNING), f"{name} must still log warnings"


def test_debug_level_still_suppresses_http_url_logging() -> None:
    # Even when the app is in DEBUG, third-party URL logging stays off so a
    # verbose local session cannot leak the bot token.
    configure_logging(level="DEBUG", json_output=False)
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
