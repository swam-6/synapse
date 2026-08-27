"""Unit tests for the outbound Telegram client using a mocked transport."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from synapse.api.telegram_client import TelegramClient


def _client(handler) -> TelegramClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return TelegramClient(SecretStr("TOKEN"), client=http)


@pytest.mark.asyncio
async def test_sends_with_markdown_v2_when_accepted() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {}})

    await _client(handler).send_message(42, "*hi*")

    assert len(seen) == 1
    assert seen[0]["parse_mode"] == "MarkdownV2"
    assert seen[0]["chat_id"] == 42


@pytest.mark.asyncio
async def test_falls_back_to_plain_text_on_bad_markup() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        calls.append(payload)
        if payload.get("parse_mode") == "MarkdownV2":
            return httpx.Response(400, json={"ok": False, "description": "bad entities"})
        return httpx.Response(200, json={"ok": True, "result": {}})

    await _client(handler).send_message(42, "unbalanced *markup")

    assert len(calls) == 2  # MarkdownV2 attempt, then plain fallback
    assert calls[0]["parse_mode"] == "MarkdownV2"
    assert "parse_mode" not in calls[1]


def test_truncate_leaves_short_text_untouched() -> None:
    from synapse.api.telegram_client import _truncate_for_telegram

    assert _truncate_for_telegram("hello") == "hello"


def test_truncate_trims_over_limit_and_marks_it() -> None:
    from synapse.api.telegram_client import (
        _TELEGRAM_MAX_MESSAGE_CHARS,
        _truncate_for_telegram,
    )

    long = "x" * 10_000
    out = _truncate_for_telegram(long)
    assert len(out) <= _TELEGRAM_MAX_MESSAGE_CHARS
    assert out.endswith("(message truncated)")


@pytest.mark.asyncio
async def test_send_message_truncates_before_sending() -> None:
    import httpx

    from synapse.api.telegram_client import _TELEGRAM_MAX_MESSAGE_CHARS, TelegramClient

    sent: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        sent.append(len(body["text"]))
        return httpx.Response(200, json={"ok": True, "result": {}})

    transport = httpx.MockTransport(handler)
    client = TelegramClient(
        SecretStr("123:ABC"), client=httpx.AsyncClient(transport=transport)
    )
    await client.send_message(42, "x" * 10_000)
    await client.aclose()

    assert sent and sent[0] <= _TELEGRAM_MAX_MESSAGE_CHARS
