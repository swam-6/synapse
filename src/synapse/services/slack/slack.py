"""Slack Web API service.

Lists conversations, reads channel/DM history, and posts messages via Slack's
async web client. A channel may be given by id (``C…``/``G…``/``D…``) or by name
(``#general`` or ``general``); names are resolved to ids before history/post
calls. The client is built lazily and cached, and ``slack-sdk`` is imported
lazily so the package imports without the SDK. A client may be injected for tests.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from synapse.errors import ExternalServiceError
from synapse.observability.logging import get_logger
from synapse.services.slack.models import SlackChannel, SlackMessage

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = get_logger(__name__)

_CHANNEL_ID_PREFIXES = ("C", "G", "D")


def looks_like_channel_id(value: str) -> bool:
    """Heuristic: whether ``value`` is a Slack channel id rather than a name."""
    return (
        len(value) >= 9
        and value[0] in _CHANNEL_ID_PREFIXES
        and value.isalnum()
        and value.upper() == value
    )


def _channel_from_api(node: dict[str, Any]) -> SlackChannel:
    return SlackChannel(id=node.get("id", ""), name=node.get("name", ""))


def _message_from_api(node: dict[str, Any]) -> SlackMessage:
    return SlackMessage(
        user=node.get("user") or node.get("bot_id") or "unknown",
        text=node.get("text", ""),
        ts=node.get("ts", ""),
    )


class SlackService:
    """Reads and sends Slack messages (``SlackGateway``)."""

    def __init__(
        self,
        *,
        token: SecretStr,
        max_history: int = 10,
        client: AsyncWebClient | None = None,
    ) -> None:
        self._token = token
        self._max_history = max_history
        self._client = client
        self._user_cache: dict[str, str] = {}  # user_id -> display name

    def _get_client(self) -> AsyncWebClient:
        if self._client is None:
            try:
                from slack_sdk.web.async_client import AsyncWebClient
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise ExternalServiceError(
                    "slack-sdk is not installed; run `poetry install`."
                ) from exc
            self._client = AsyncWebClient(token=self._token.get_secret_value())
        return self._client

    async def list_channels(self) -> list[SlackChannel]:
        """Return public and private conversations the bot can access."""
        client = self._get_client()
        try:
            response = await client.conversations_list(
                types="public_channel,private_channel", limit=200
            )
        except Exception as exc:  # noqa: BLE001 - normalise Slack SDK errors
            raise ExternalServiceError(f"Failed to list Slack channels: {exc}") from exc
        return [_channel_from_api(node) for node in response.get("channels", [])]

    async def _resolve_channel(self, channel: str) -> str:
        """Return a channel id for ``channel`` given as an id or a name."""
        if looks_like_channel_id(channel):
            return channel
        wanted = channel.lstrip("#").lower()
        for available in await self.list_channels():
            if available.name.lower() == wanted:
                return available.id
        raise ExternalServiceError(f"No Slack channel named {channel!r} was found.")

    async def _resolve_user(self, user_id: str) -> str:
        """Return a human-readable name for a Slack user id, with caching."""
        if not user_id or user_id == "unknown":
            return user_id
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            client = self._get_client()
            info = await client.users_info(user=user_id)
            profile = info.get("user", {}).get("profile", {})
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user_id
            )
        except Exception:  # noqa: BLE001
            name = user_id  # fall back to raw ID on any error
        self._user_cache[user_id] = name
        return name

    async def _resolve_mentions_in_text(self, text: str) -> str:
        """Replace all <@USERID> mention tokens in ``text`` with display names."""
        mention_ids = re.findall(r"<@([A-Z0-9]+)>", text)
        for uid in set(mention_ids):
            name = await self._resolve_user(uid)
            text = text.replace(f"<@{uid}>", name)
        return text

    async def read_messages(self, *, channel: str, limit: int) -> list[SlackMessage]:
        """Return up to ``limit`` recent messages from ``channel`` (id or name)."""
        client = self._get_client()
        channel_id = await self._resolve_channel(channel)
        try:
            response = await client.conversations_history(
                channel=channel_id, limit=min(limit, self._max_history)
            )
        except ExternalServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise Slack SDK errors
            raise ExternalServiceError(f"Failed to read Slack messages: {exc}") from exc
        raw_messages = response.get("messages", [])
        resolved = []
        for node in raw_messages:
            raw_user = node.get("user") or node.get("bot_id") or "unknown"
            display_name = await self._resolve_user(raw_user)
            raw_text = node.get("text", "")
            # Resolve <@USERID> mention tokens embedded in the message text
            clean_text = await self._resolve_mentions_in_text(raw_text)
            resolved.append(SlackMessage(
                user=display_name,
                text=clean_text,
                ts=node.get("ts", ""),
            ))
        return resolved

    async def send_message(self, *, channel: str, text: str) -> None:
        """Post ``text`` to ``channel`` (id or name)."""
        client = self._get_client()
        channel_id = await self._resolve_channel(channel)
        try:
            await client.chat_postMessage(channel=channel_id, text=text)
        except ExternalServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise Slack SDK errors
            raise ExternalServiceError(f"Failed to send Slack message: {exc}") from exc
        logger.info("slack_message_sent", channel=channel_id)

    async def delete_message(self, *, channel: str, ts: str) -> None:
        """Delete the message at ``ts`` in ``channel`` (id or name)."""
        client = self._get_client()
        channel_id = await self._resolve_channel(channel)
        try:
            await client.chat_delete(channel=channel_id, ts=ts)
        except ExternalServiceError:
            raise
        except Exception as exc:  # noqa: BLE001
            if "cant_delete_message" in str(exc):
                raise ExternalServiceError(
                    "Slack blocked deletion. A bot can only delete its own messages."
                ) from exc
            raise ExternalServiceError(f"Failed to delete Slack message: {exc}") from exc
        logger.info("slack_message_deleted", channel=channel_id, ts=ts)
