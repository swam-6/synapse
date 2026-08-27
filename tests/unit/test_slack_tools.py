"""Unit tests for the Slack worker tools using a fake gateway."""

from __future__ import annotations

import pytest

from synapse.errors import ExternalServiceError
from synapse.services.slack.models import SlackChannel, SlackMessage
from synapse.tools.slack import build_slack_tools


class _FakeGateway:
    def __init__(self, *, channels=None, messages=None, error=None):
        self._channels = channels or []
        self._messages = messages or []
        self._error = error
        self.posted: list[dict] = []

    async def list_channels(self):
        if self._error:
            raise self._error
        return self._channels

    async def read_messages(self, *, channel, limit):
        if self._error:
            raise self._error
        return self._messages

    async def send_message(self, *, channel, text):
        if self._error:
            raise self._error
        self.posted.append({"channel": channel, "text": text})


def _tools(gateway) -> dict:
    return {t.name: t for t in build_slack_tools(gateway)}


@pytest.mark.asyncio
async def test_list_channels_formats() -> None:
    gw = _FakeGateway(channels=[SlackChannel(id="C1", name="general")])
    result = await _tools(gw)["list_channels"].ainvoke({})
    assert "#general" in result and "id=C1" in result


@pytest.mark.asyncio
async def test_read_messages_oldest_first() -> None:
    gw = _FakeGateway(
        messages=[
            SlackMessage(user="U2", text="second", ts="2"),
            SlackMessage(user="U1", text="first", ts="1"),
        ]
    )
    result = await _tools(gw)["read_messages"].ainvoke({"channel": "#general"})
    # Gateway returns newest-first; the tool presents oldest-first.
    assert result.index("first") < result.index("second")


@pytest.mark.asyncio
async def test_send_message_confirms_and_posts() -> None:
    gw = _FakeGateway()
    result = await _tools(gw)["send_message"].ainvoke({"channel": "#general", "text": "hi team"})
    assert "Message posted to #general" in result
    assert gw.posted == [{"channel": "#general", "text": "hi team"}]


@pytest.mark.asyncio
async def test_send_message_reports_error() -> None:
    gw = _FakeGateway(error=ExternalServiceError("not_in_channel"))
    result = await _tools(gw)["send_message"].ainvoke({"channel": "#x", "text": "hi"})
    assert "Could not send the message" in result and "not_in_channel" in result
    assert gw.posted == []
