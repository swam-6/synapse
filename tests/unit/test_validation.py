"""Unit tests for input validation helpers."""

from __future__ import annotations

import pytest

from synapse.utils.validation import is_probably_email


@pytest.mark.parametrize(
    "value",
    ["alice@example.com", "a.b+tag@sub.example.co.uk", "  spaced@example.com  "],
)
def test_valid_addresses(value: str) -> None:
    assert is_probably_email(value) is True


@pytest.mark.parametrize(
    "value",
    ["Alice", "alice@", "@example.com", "alice@example", "alice example.com", ""],
)
def test_invalid_addresses(value: str) -> None:
    assert is_probably_email(value) is False
