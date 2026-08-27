"""Unit tests for Gmail payload parsing helpers (no network, no SDK)."""

from __future__ import annotations

import base64

from synapse.services.email.gmail import _decode_body, _header


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def test_header_lookup_is_case_insensitive() -> None:
    headers = [{"name": "From", "value": "bob@x.com"}, {"name": "Subject", "value": "Hi"}]
    assert _header(headers, "from") == "bob@x.com"
    assert _header(headers, "SUBJECT") == "Hi"
    assert _header(headers, "Missing") == ""


def test_decode_body_prefers_plain_text_part() -> None:
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64("<b>hi</b>")}},
            {"mimeType": "text/plain", "body": {"data": _b64("plain hi")}},
        ],
    }
    assert _decode_body(payload) == "plain hi"


def test_decode_body_falls_back_to_top_level_body() -> None:
    payload = {"mimeType": "text/plain", "body": {"data": _b64("single part body")}}
    assert _decode_body(payload) == "single part body"


def test_decode_body_returns_empty_when_no_text() -> None:
    payload = {"mimeType": "image/png", "body": {}}
    assert _decode_body(payload) == ""
