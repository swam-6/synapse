"""Capability interface for the Slack integration (Dependency Inversion)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from synapse.services.slack.models import SlackChannel, SlackMessage


@runtime_checkable
class SlackGateway(Protocol):
    """Lists conversations, reads messages, and sends messages."""

    async def list_channels(self) -> list[SlackChannel]:
        """Return the conversations the bot can access."""
        ...

    async def read_messages(self, *, channel: str, limit: int) -> list[SlackMessage]:
        """Return the most recent messages from ``channel`` (id or name)."""
        ...

    async def send_message(self, *, channel: str, text: str) -> None:
        """Post ``text`` to ``channel`` (id or name)."""
        ...

    async def delete_message(self, *, channel: str, ts: str) -> None:
        """Delete the message at ``ts`` in ``channel`` (id or name)."""
        ...
