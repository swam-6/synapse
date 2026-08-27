"""Chain-of-thought must never reach the user.

Reasoning models (gpt-oss, qwen3, deepseek-r1) return content as a list of typed
blocks. Stringifying that list emitted the model's private reasoning — plus a
Python repr — into the Telegram reply.
"""

from __future__ import annotations

from synapse.graph.runner import message_text


def test_plain_string_passes_through() -> None:
    assert message_text("You're free at 3 PM.") == "You're free at 3 PM."


def test_reasoning_block_is_dropped_and_text_kept() -> None:
    content = [
        {"type": "reasoning", "reasoning": "We need to check the calendar. We..."},
        {"type": "text", "text": "You're free tomorrow at 3 PM."},
    ]
    assert message_text(content) == "You're free tomorrow at 3 PM."


def test_thinking_variants_are_dropped() -> None:
    content = [
        {"type": "thinking", "thinking": "We should call list_events..."},
        {"type": "redacted_thinking", "data": "xxx"},
        {"type": "text", "text": "Done."},
    ]
    assert message_text(content) == "Done."


def test_multiple_text_blocks_are_joined() -> None:
    content = [{"type": "text", "text": "Hello "}, {"type": "text", "text": "world."}]
    assert message_text(content) == "Hello world."


def test_never_emits_python_repr_of_blocks() -> None:
    content = [{"type": "text", "text": "Clean."}]
    result = message_text(content)
    # The old code produced "[{'type': 'text', ...}]" — the repr must not survive.
    assert "{" not in result and "'type'" not in result
    assert result == "Clean."


def test_bare_strings_in_list_are_kept() -> None:
    assert message_text(["a", "b"]) == "ab"


def test_unknown_shape_falls_back_to_str() -> None:
    assert message_text(42) == "42"
