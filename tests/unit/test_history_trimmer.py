"""Unit tests for the Manager's history-trimming ``pre_model_hook``.

The trimmer caps the message history fed to the Manager on each LLM call — the
dominant, unbounded token cost, since the supervisor re-sends its whole history
on every one of a turn's several calls. These tests pin the properties that keep
it both effective and safe for a strict provider (Groq): it returns the trimmed
view under ``llm_input_messages`` (so the checkpoint is untouched), keeps the
most recent turn, begins on a human message, and never orphans a tool result.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from synapse.agents.manager import _build_history_trimmer


def _supervisor_turn(n: int, *, words: int = 1) -> list:
    """A completed supervisor turn: user, handoff call, handoff result, answer."""
    filler = ("x%d " % n) * words
    return [
        HumanMessage(content=f"question {n} {filler}", id=f"h{n}"),
        AIMessage(
            content="",
            id=f"a{n}",
            tool_calls=[{"name": "transfer_to_x", "args": {}, "id": f"t{n}", "type": "tool_call"}],
        ),
        ToolMessage(content="transferred", tool_call_id=f"t{n}", id=f"tm{n}"),
        AIMessage(content=f"answer {n} {filler}", id=f"f{n}"),
    ]


def _is_valid_ordering(messages: list) -> bool:
    """Every ToolMessage must directly follow the AIMessage that called it."""
    for i, m in enumerate(messages):
        if isinstance(m, ToolMessage):
            prev = messages[i - 1] if i > 0 else None
            if not (
                isinstance(prev, AIMessage)
                and any(tc["id"] == m.tool_call_id for tc in (prev.tool_calls or []))
            ):
                return False
    return True


def test_returns_llm_input_messages_without_touching_state() -> None:
    hook = _build_history_trimmer(4000)
    out = hook({"messages": _supervisor_turn(1)})
    # The hook feeds the model via llm_input_messages and must NOT emit a
    # `messages` key, which would rewrite the persisted history.
    assert set(out) == {"llm_input_messages"}


def test_generous_budget_keeps_everything() -> None:
    msgs = _supervisor_turn(1) + _supervisor_turn(2)
    out = _build_history_trimmer(4000)({"messages": msgs})["llm_input_messages"]
    assert len(out) == len(msgs)


def test_tight_budget_keeps_recent_tail_only() -> None:
    # Six turns of sizeable messages; a moderate budget must drop the oldest.
    msgs = [m for n in range(6) for m in _supervisor_turn(n, words=30)]
    out = _build_history_trimmer(240)({"messages": msgs})["llm_input_messages"]

    assert 0 < len(out) < len(msgs)              # trimming actually happened
    assert isinstance(out[0], HumanMessage)      # begins on a human boundary
    assert _is_valid_ordering(out)               # no orphaned tool result
    # The most recent turn is always retained (strategy="last").
    assert out[-1].content == msgs[-1].content


def test_never_starts_on_a_dangling_tool_message() -> None:
    # A budget that can only fit part of the last turn must still not begin on a
    # ToolMessage (which Groq rejects with 400 tool_use_failed).
    msgs = [m for n in range(4) for m in _supervisor_turn(n, words=20)]
    out = _build_history_trimmer(80)({"messages": msgs})["llm_input_messages"]
    assert all(not isinstance(out[0], ToolMessage) for _ in [0]) if out else True
