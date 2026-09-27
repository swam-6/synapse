"""Structured logging configuration built on :mod:`structlog`.

The whole application logs through ``structlog`` so that every record is a typed
event dict carrying the active request id (from
:mod:`synapse.observability.context`). In production the final renderer emits
JSON for log aggregation; in development it emits a colourised console view.

:func:`configure_logging` is idempotent and must be called once at process
startup before any logger is used.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from synapse.observability.context import get_request_id


def _add_request_id(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """structlog processor that injects the current request id into each event."""
    request_id = get_request_id()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    """Configure ``structlog`` and the stdlib logging bridge process-wide.

    Args:
        level: Minimum level name (e.g. ``"INFO"``) for records to be emitted.
        json_output: When ``True`` render events as JSON (production); when
            ``False`` render a human-friendly console view (development).

    The call is safe to invoke more than once; the last configuration wins.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route the stdlib root logger (used by uvicorn, httpx, google clients)
    # through the same stream and level so output stays uniform.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.getLevelNamesMapping()[level],
        force=True,
    )
    _silence_secret_leaking_loggers()


#: Third-party loggers that echo full request URLs at INFO. The Telegram Bot API
#: embeds the bot token in the URL path (``/bot<TOKEN>/sendMessage``), so their
#: INFO output would write the token into our logs on every call. Raising them to
#: WARNING keeps errors visible while never emitting a credential.
_URL_LOGGING_LIBRARIES = ("httpx", "httpcore")


def _silence_secret_leaking_loggers() -> None:
    """Prevent third-party HTTP loggers from logging credential-bearing URLs."""
    for name in _URL_LOGGING_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound ``structlog`` logger, optionally named for its module.

    Usage: ``logger = get_logger(__name__)``.
    """
    return structlog.get_logger(name)
