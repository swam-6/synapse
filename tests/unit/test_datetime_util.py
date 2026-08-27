"""Unit tests for ISO 8601 datetime parsing helpers."""

from __future__ import annotations

from datetime import timezone

import pytest

from synapse.utils.datetime import parse_iso8601, to_rfc3339


def test_parses_utc_z_suffix() -> None:
    parsed = parse_iso8601("2026-07-20T09:00:00Z")
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_naive_value_defaults_to_utc() -> None:
    parsed = parse_iso8601("2026-07-20T09:00:00")
    assert parsed.tzinfo == timezone.utc


def test_preserves_explicit_offset() -> None:
    parsed = parse_iso8601("2026-07-20T09:00:00+05:30")
    assert parsed.utcoffset().total_seconds() == 5.5 * 3600


def test_invalid_value_raises() -> None:
    with pytest.raises(ValueError):
        parse_iso8601("not-a-date")


def test_to_rfc3339_roundtrip() -> None:
    text = to_rfc3339(parse_iso8601("2026-07-20T09:00:00Z"))
    assert text.startswith("2026-07-20T09:00:00")
