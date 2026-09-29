"""LangChain tools for the Slack worker.

Thin, validated wrappers over the :class:`SlackGateway`. On invalid input or a
service failure a tool returns an agent-readable message rather than raising.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from synapse.errors import ExternalServiceError
from synapse.observability.logging import get_logger
from synapse.services.slack.models import SlackChannel, SlackMessage
from synapse.services.slack.protocols import SlackGateway

logger = get_logger(__name__)


class SendMessageInput(BaseModel):
    """Validated arguments for posting a Slack message."""

    channel: str = Field(min_length=1, description="Channel id or name (e.g. #general).")
    text: str = Field(min_length=1, description="The message text to post.")


class DeleteMessageInput(BaseModel):
    """Validated arguments for deleting a Slack message."""

    channel: str = Field(min_length=1, description="Channel id or name (e.g. #general).")
    ts: str = Field(min_length=1, description="The exact timestamp (ts) of the message to delete.")


def _format_channels(channels: list[SlackChannel]) -> str:
    if not channels:
        return "The bot is not a member of any accessible channels."
    return "\n".join(f"#{c.name} (id={c.id})" for c in channels)


def _format_messages(messages: list[SlackMessage]) -> str:
    if not messages:
        return "No messages found in that channel."
    # Slack returns newest first; present oldest-first for readability.
    return "\n".join(f"[{m.ts}] {m.user}: {m.text}" for m in reversed(messages))


def build_slack_tools(gateway: SlackGateway) -> list[BaseTool]:
    """Build the Slack worker's tools bound to ``gateway``."""

    @tool
    async def list_channels() -> str:
        """List the Slack channels the assistant can read from or post to."""
        try:
            channels = await gateway.list_channels()
        except ExternalServiceError as exc:
            logger.warning("tool_list_channels_failed", error=str(exc))
            return f"Could not list channels: {exc}"
        return _format_channels(channels)

    @tool
    async def read_messages(channel: str, limit: int = 10) -> str:
        """Read recent messages from a Slack channel (by id or name).

        Returns up to ``limit`` messages, oldest first, as ``author: text``.
        """
        capped = max(1, min(limit, 100))
        try:
            messages = await gateway.read_messages(channel=channel, limit=capped)
        except ExternalServiceError as exc:
            logger.warning("tool_read_messages_failed", error=str(exc))
            return f"Could not read #{channel}: {exc}"
        return _format_messages(messages)

    @tool(args_schema=SendMessageInput)
    async def send_message(channel: str, text: str) -> str:
        """Post a message to a Slack channel (by id or name)."""
        try:
            await gateway.send_message(channel=channel, text=text)
        except ExternalServiceError as exc:
            logger.warning("tool_send_message_failed", error=str(exc))
            return f"Could not send the message: {exc}"
        return f"Message posted to {channel}."

    @tool(args_schema=DeleteMessageInput)
    async def delete_message(channel: str, ts: str) -> str:
        """Delete a specific message from a Slack channel.
        
        You must provide the exact timestamp (ts) of the message, which you can find
        by reading the channel messages first (it's the value in brackets like [1712345678.123456]).
        """
        try:
            await gateway.delete_message(channel=channel, ts=ts)
        except ExternalServiceError as exc:
            logger.warning("tool_delete_message_failed", error=str(exc))
            return f"Could not delete the message: {exc}"
        return f"Message {ts} deleted from {channel}."

    return [list_channels, read_messages, send_message, delete_message]
