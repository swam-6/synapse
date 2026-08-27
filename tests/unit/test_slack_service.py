"""Unit tests for the Slack service with an injected fake web client."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from synapse.errors import ExternalServiceError
from synapse.services.slack.slack import SlackService, looks_like_channel_id


class _FakeWebClient:
    """Minimal async stand-in for slack_sdk AsyncWebClient returning dicts."""

    def __init__(self) -> None:
        self.posted: list[dict] = []

    async def conversations_list(self, **kwargs: object) -> dict:
        return {"channels": [{"id": "C123456789", "name": "general"}]}

    async def conversations_history(self, *, channel: str, limit: int) -> dict:
        return {
            "messages": [
                {"user": "U2", "text": "second", "ts": "2"},
                {"user": "U1", "text": "first", "ts": "1"},
            ]
        }

    async def chat_postMessage(self, *, channel: str, text: str) -> dict:
        self.posted.append({"channel": channel, "text": text})
        return {"ok": True}


def _service(client) -> SlackService:
    return SlackService(token=SecretStr("xoxb-test"), max_history=10, client=client)


@pytest.mark.parametrize("value,expected", [
    ("C123456789", True), ("G012345678", True), ("D087654321", True),
    ("general", False), ("#general", False), ("C123", False), ("c123456789", False),
])
def test_looks_like_channel_id(value: str, expected: bool) -> None:
    assert looks_like_channel_id(value) is expected


@pytest.mark.asyncio
async def test_read_messages_by_name_resolves_and_returns() -> None:
    messages = await _service(_FakeWebClient()).read_messages(channel="#general", limit=10)
    assert [m.text for m in messages] == ["second", "first"]
    assert messages[0].user == "U2"


@pytest.mark.asyncio
async def test_read_messages_by_id_skips_resolution() -> None:
    messages = await _service(_FakeWebClient()).read_messages(channel="C123456789", limit=5)
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_send_message_resolves_name_to_id() -> None:
    client = _FakeWebClient()
    await _service(client).send_message(channel="#general", text="hello")
    assert client.posted == [{"channel": "C123456789", "text": "hello"}]


@pytest.mark.asyncio
async def test_unknown_channel_name_raises() -> None:
    with pytest.raises(ExternalServiceError, match="No Slack channel named"):
        await _service(_FakeWebClient()).read_messages(channel="#missing", limit=5)
