"""Unit tests for the observability callback handler."""

from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.outputs import LLMResult

from synapse.observability.callbacks import UsageCallbackHandler, extract_token_usage


def test_extract_token_usage_from_llm_output() -> None:
    result = LLMResult(
        generations=[],
        llm_output={"token_usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}},
    )
    usage = extract_token_usage(result)
    assert usage == {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}


def test_extract_token_usage_absent_returns_none() -> None:
    assert extract_token_usage(LLMResult(generations=[], llm_output={})) is None


@pytest.mark.asyncio
async def test_tool_timing_tracks_and_clears() -> None:
    handler = UsageCallbackHandler()
    run_id = uuid4()
    await handler.on_tool_start({"name": "send_email"}, "{}", run_id=run_id)
    assert run_id in handler._tool_starts
    await handler.on_tool_end("ok", run_id=run_id)
    assert run_id not in handler._tool_starts  # cleared after end


@pytest.mark.asyncio
async def test_tool_end_without_start_is_safe() -> None:
    handler = UsageCallbackHandler()
    # Must not raise even if no matching start was recorded.
    await handler.on_tool_end("ok", run_id=uuid4())


@pytest.mark.asyncio
async def test_turn_usage_accumulates_across_calls() -> None:
    """One question fans out into many LLM calls; the turn total is the real cost."""
    handler = UsageCallbackHandler()
    for _ in range(3):
        await handler.on_llm_end(
            LLMResult(
                generations=[],
                llm_output={"token_usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}},
            )
        )
    assert handler.turn_usage() == {
        "llm_calls": 3, "input_tokens": 300, "output_tokens": 60, "total_tokens": 360,
    }


@pytest.mark.asyncio
async def test_turn_usage_counts_calls_without_reported_tokens() -> None:
    handler = UsageCallbackHandler()
    await handler.on_llm_end(LLMResult(generations=[], llm_output={}))
    assert handler.turn_usage()["llm_calls"] == 1
    assert handler.turn_usage()["total_tokens"] == 0
