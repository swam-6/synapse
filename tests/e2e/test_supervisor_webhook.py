"""End-to-end test of the integrated channel + supervisor path.

Drives the real FastAPI webhook whose graph is the actual Manager supervisor
(built with scripted, key-free models). Proves that an inbound Telegram message
is delegated to a worker and the Manager's aggregated reply is delivered back —
Phase 1 and Phase 2 working together.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from synapse.agents.manager import build_manager_graph
from synapse.api.app import create_app
from synapse.api.security import SECRET_TOKEN_HEADER
from synapse.config.settings import Settings, get_settings
from tests.support.scripted_model import (
    ScriptedChatModel,
    ScriptedModelFactory,
    tool_call,
)
from tests.support.workers import TEST_AGENT_NAME, build_test_worker_spec

_SECRET = "test-secret-token"
_FINAL_REPLY = "It is 2026-07-15 in UTC."


class _RecordingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    async def aclose(self) -> None:
        return None


def _supervisor_builder(checkpointer: BaseCheckpointSaver, settings: Settings) -> object:
    factory = ScriptedModelFactory(
        [
            ScriptedChatModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[tool_call(f"transfer_to_{TEST_AGENT_NAME}", "m1")],
                    ),
                    AIMessage(content=_FINAL_REPLY),
                ]
            ),
            ScriptedChatModel(
                responses=[
                    AIMessage(content="", tool_calls=[tool_call("echo_tool", "w1", {"text": "x"})]),
                    AIMessage(content="x"),
                ]
            ),
        ]
    )
    return build_manager_graph(
        checkpointer,
        llm_factory=factory,
        settings=settings,
        worker_specs=[build_test_worker_spec(settings)],
    )


@pytest.fixture
async def harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[AsyncClient, _RecordingSender, FastAPI]]:
    monkeypatch.setenv("SYNAPSE_SQLITE_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setenv("SYNAPSE_TELEGRAM_WEBHOOK_SECRET", _SECRET)
    monkeypatch.setenv("SYNAPSE_LOG_JSON", "false")
    get_settings.cache_clear()

    app = create_app(graph_builder=_supervisor_builder)
    async with app.router.lifespan_context(app):
        sender = _RecordingSender()
        app.state.context = dataclasses.replace(app.state.context, telegram=sender)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, sender, app
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_webhook_delegates_and_delivers_manager_reply(
    harness: tuple[AsyncClient, _RecordingSender, FastAPI],
) -> None:
    client, sender, app = harness
    body = {
        "update_id": 1,
        "message": {"message_id": 1, "chat": {"id": 777}, "text": "what time is it?"},
    }

    response = await client.post(
        "/telegram/webhook", json=body, headers={SECRET_TOKEN_HEADER: _SECRET}
    )
    assert response.status_code == 200
    await app.state.context.background.drain(timeout=5.0)

    assert len(sender.sent) == 1
    chat_id, text = sender.sent[0]
    assert chat_id == 777
    assert text == _FINAL_REPLY  # the Manager's aggregated reply, not the worker's raw output
