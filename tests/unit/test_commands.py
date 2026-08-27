"""Unit tests for Telegram slash-command handling."""

from __future__ import annotations

import pytest

from synapse.api.commands import handle_command, is_command


class _SpyCheckpointer:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


@pytest.mark.parametrize("text,expected", [
    ("/reset", True), ("/help", True), ("/start", True),
    ("hello", False), ("what's on my calendar?", False), ("", False),
])
def test_is_command(text: str, expected: bool) -> None:
    assert is_command(text) is expected


@pytest.mark.asyncio
async def test_reset_deletes_only_this_thread() -> None:
    cp = _SpyCheckpointer()
    reply = await handle_command("/reset", thread_id="42", checkpointer=cp)
    assert cp.deleted == ["42"]
    assert "cleared" in reply.lower()
    # Must reassure the user their real data is safe.
    assert "untouched" in reply.lower()


@pytest.mark.asyncio
async def test_reset_tolerates_group_suffix_and_args() -> None:
    cp = _SpyCheckpointer()
    await handle_command("/reset@SynapseV100bot", thread_id="7", checkpointer=cp)
    await handle_command("/reset please", thread_id="8", checkpointer=cp)
    assert cp.deleted == ["7", "8"]


@pytest.mark.asyncio
async def test_start_and_help_do_not_touch_memory() -> None:
    cp = _SpyCheckpointer()
    for cmd in ("/start", "/help", "/START"):
        reply = await handle_command(cmd, thread_id="1", checkpointer=cp)
        assert "Synapse" in reply
    assert cp.deleted == []


@pytest.mark.asyncio
async def test_unknown_command_is_reported() -> None:
    cp = _SpyCheckpointer()
    reply = await handle_command("/wat", thread_id="1", checkpointer=cp)
    assert "/help" in reply
    assert cp.deleted == []
