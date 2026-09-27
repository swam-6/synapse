"""End-to-end tests for the Telegram webhook loop.

The real application is driven through its ASGI interface with a live
(temp-file) checkpointer and the actual graph; only the outbound Telegram sender
is replaced with a recorder so the reply can be asserted. This exercises secret
verification, validation, idempotency, background dispatch, and delivery together.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from langgraph.checkpoint.base import BaseCheckpointSaver

from synapse.api.app import create_app
from synapse.api.security import SECRET_TOKEN_HEADER
from synapse.config.settings import Settings, get_settings
from synapse.graph.builder import build_echo_graph


def _echo_graph_builder(checkpointer: BaseCheckpointSaver, settings: Settings) -> object:
    """Channel tests use the LLM-free echo graph (no provider key needed)."""
    return build_echo_graph(checkpointer)

_SECRET = "test-secret-token"


class _RecordingSender:
    """Captures outbound messages instead of calling Telegram."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    async def aclose(self) -> None:
        return None


def _update(update_id: int, chat_id: int, text: str | None) -> dict:
    message: dict = {"message_id": update_id, "chat": {"id": chat_id}}
    if text is not None:
        message["text"] = text
    return {"update_id": update_id, "message": message}


@pytest.fixture
async def harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[AsyncClient, _RecordingSender, FastAPI]]:
    """Start the app through its lifespan with a recording sender injected."""
    monkeypatch.setenv("SYNAPSE_SQLITE_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setenv("SYNAPSE_TELEGRAM_WEBHOOK_SECRET", _SECRET)
    monkeypatch.setenv("SYNAPSE_LOG_JSON", "false")
    get_settings.cache_clear()

    app = create_app(graph_builder=_echo_graph_builder)
    async with app.router.lifespan_context(app):
        sender = _RecordingSender()
        app.state.context = dataclasses.replace(app.state.context, telegram=sender)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, sender, app
    get_settings.cache_clear()


async def _drain(app: FastAPI) -> None:
    await app.state.context.background.drain(timeout=5.0)


async def _post(client: AsyncClient, body: dict, *, secret: str | None = _SECRET) -> int:
    headers = {SECRET_TOKEN_HEADER: secret} if secret is not None else {}
    response = await client.post("/telegram/webhook", json=body, headers=headers)
    return response.status_code


@pytest.mark.asyncio
async def test_health_endpoint(
    harness: tuple[AsyncClient, _RecordingSender, FastAPI],
) -> None:
    client, _, _ = harness
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_message_produces_reply(
    harness: tuple[AsyncClient, _RecordingSender, FastAPI],
) -> None:
    client, sender, app = harness

    status = await _post(client, _update(1, 555, "hello"))
    assert status == 200
    await _drain(app)

    assert len(sender.sent) == 1
    chat_id, text = sender.sent[0]
    assert chat_id == 555
    assert "turn 1" in text and "hello" in text


@pytest.mark.asyncio
async def test_invalid_secret_is_rejected(
    harness: tuple[AsyncClient, _RecordingSender, FastAPI],
) -> None:
    client, sender, _ = harness
    status = await _post(client, _update(2, 555, "hi"), secret="wrong")
    assert status == 403
    assert sender.sent == []


@pytest.mark.asyncio
async def test_duplicate_update_processed_once(
    harness: tuple[AsyncClient, _RecordingSender, FastAPI],
) -> None:
    client, sender, app = harness

    assert await _post(client, _update(7, 555, "hi")) == 200
    assert await _post(client, _update(7, 555, "hi")) == 200  # redelivery
    await _drain(app)

    assert len(sender.sent) == 1  # deduped by update_id


@pytest.mark.asyncio
async def test_non_text_update_is_acknowledged_without_reply(
    harness: tuple[AsyncClient, _RecordingSender, FastAPI],
) -> None:
    client, sender, app = harness
    status = await _post(client, _update(3, 555, None))
    assert status == 200
    await _drain(app)
    assert sender.sent == []
