"""Unit tests for MarkdownV2 escaping."""

from __future__ import annotations

from synapse.utils.markdown import escape_markdown_v2


def test_plain_text_is_unchanged() -> None:
    assert escape_markdown_v2("hello world") == "hello world"


def test_formatting_characters_are_escaped() -> None:
    assert escape_markdown_v2("a_b*c") == "a\\_b\\*c"


def test_punctuation_specials_are_escaped() -> None:
    assert escape_markdown_v2("Done! (see #1).") == "Done\\! \\(see \\#1\\)\\."


def test_every_reserved_character_is_escaped() -> None:
    reserved = r"_*[]()~`>#+-=|{}.!"
    escaped = escape_markdown_v2(reserved)
    # Each reserved char becomes a backslash + itself.
    assert escaped == "".join(f"\\{ch}" for ch in reserved)
