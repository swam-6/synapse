"""Request-scoped correlation context.

A single request-id follows one Telegram update through the webhook handler,
the Manager graph, every delegated worker, and each tool call, so all log lines
for that turn can be correlated. The id lives in a :class:`contextvars.ContextVar`,
which is safe under ``asyncio`` concurrency: each task sees its own value.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_request_id_var: ContextVar[str | None] = ContextVar("synapse_request_id", default=None)


def new_request_id() -> str:
    """Generate a fresh, unique request id."""
    return uuid.uuid4().hex


def bind_request_id(request_id: str) -> Token[str | None]:
    """Bind ``request_id`` to the current context.

    Returns the reset :class:`~contextvars.Token`; pass it to
    :func:`reset_request_id` to restore the previous value (important when a
    single worker reuses a task, so ids do not leak across turns).
    """
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the request id to its value before the matching :func:`bind_request_id`."""
    _request_id_var.reset(token)


def get_request_id() -> str | None:
    """Return the request id bound to the current context, if any."""
    return _request_id_var.get()
