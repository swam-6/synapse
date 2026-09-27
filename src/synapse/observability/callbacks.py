"""LangChain callback handler for execution observability.

Attached to each graph invocation, :class:`UsageCallbackHandler` logs the agent
execution timeline (tool starts/ends with latency) and LLM token usage. Because
it runs in the same async context as the turn, every line it emits carries the
turn's ``request_id`` automatically. Observability must never break a turn, so
every handler method is defensive and swallows its own errors.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from synapse.observability.logging import get_logger

logger = get_logger(__name__)


def extract_token_usage(response: LLMResult) -> dict[str, int] | None:
    """Extract a normalised token-usage dict from an LLM result, if present.

    Handles both the provider ``llm_output['token_usage']`` shape and the
    per-message ``usage_metadata`` shape. Returns ``None`` when no usage is
    reported (e.g. test/scripted models).
    """
    output = getattr(response, "llm_output", None) or {}
    usage = output.get("token_usage") or output.get("usage")
    if usage:
        return {
            "input_tokens": int(usage.get("prompt_tokens", usage.get("input_tokens", 0))),
            "output_tokens": int(usage.get("completion_tokens", usage.get("output_tokens", 0))),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }

    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    found = False
    for generations in getattr(response, "generations", []) or []:
        for generation in generations:
            message = getattr(generation, "message", None)
            meta = getattr(message, "usage_metadata", None)
            if meta:
                found = True
                totals["input_tokens"] += int(meta.get("input_tokens", 0))
                totals["output_tokens"] += int(meta.get("output_tokens", 0))
                totals["total_tokens"] += int(meta.get("total_tokens", 0))
    return totals if found else None


class UsageCallbackHandler(AsyncCallbackHandler):
    """Logs tool latency and LLM token usage during a turn."""

    def __init__(self) -> None:
        self._tool_starts: dict[UUID, tuple[str, float]] = {}
        # Accumulated across the turn. A single question fans out into several
        # sequential LLM calls (supervisor -> worker -> tools -> verification),
        # so the per-call numbers alone never show what a turn actually costs.
        self.llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0

    def turn_usage(self) -> dict[str, int]:
        """Return this turn's accumulated LLM usage."""
        return {
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }

    async def on_tool_start(
        self, serialized: dict[str, Any], input_str: str, *, run_id: UUID, **kwargs: Any
    ) -> None:
        name = (serialized or {}).get("name", "tool")
        self._tool_starts[run_id] = (name, time.monotonic())

    async def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        started = self._tool_starts.pop(run_id, None)
        if started is None:
            return
        name, start = started
        logger.info("tool_executed", tool=name, duration_ms=round((time.monotonic() - start) * 1000, 1))

    async def on_tool_error(
        self, error: BaseException, *, run_id: UUID, **kwargs: Any
    ) -> None:
        started = self._tool_starts.pop(run_id, None)
        name = started[0] if started else "tool"
        logger.warning("tool_error", tool=name, error=str(error))

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        self.llm_calls += 1
        usage = extract_token_usage(response)
        if usage is None:
            return
        self.input_tokens += usage["input_tokens"]
        self.output_tokens += usage["output_tokens"]
        self.total_tokens += usage["total_tokens"]
        logger.info("llm_token_usage", **usage)
