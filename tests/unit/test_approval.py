"""Unit tests for the approval helpers."""

from __future__ import annotations

import pytest
from langchain_core.tools import tool

from synapse.agents.approval import ApprovalPolicy, apply_approvals, is_affirmative


@pytest.mark.parametrize("value", ["yes", "Y", " approve ", "confirm", "ok", True, {"approved": True}])
def test_affirmative_values(value: object) -> None:
    assert is_affirmative(value) is True


@pytest.mark.parametrize("value", ["no", "n", "cancel", "stop", "", False, {"approved": False}])
def test_non_affirmative_values(value: object) -> None:
    assert is_affirmative(value) is False


@tool
async def _send(to: str) -> str:
    """Send to a recipient."""
    return f"sent to {to}"


@tool
async def _read() -> str:
    """Read something."""
    return "read"


def test_apply_approvals_disabled_passes_through() -> None:
    tools = apply_approvals(
        [_send, _read], [ApprovalPolicy("_send", lambda a: "x")], enabled=False
    )
    assert tools == [_send, _read]  # unchanged identities


def test_apply_approvals_wraps_only_named_tool() -> None:
    wrapped = apply_approvals(
        [_send, _read], [ApprovalPolicy("_send", lambda a: "Send?")], enabled=True
    )
    by_name = {t.name: t for t in wrapped}
    assert by_name["_send"] is not _send  # wrapped
    assert by_name["_read"] is _read  # untouched
    # Schema and description are preserved on the wrapped tool.
    assert by_name["_send"].description == _send.description
    assert by_name["_send"].args_schema == _send.args_schema


@pytest.mark.parametrize("reply", [
    "yes", "Yes!", "yes please", "yeah", "yep", "sure", "sure, go for it",
    "ok", "okay", "confirm", "approve", "proceed", "go ahead", "do it", "1",
])
def test_natural_affirmatives_are_accepted(reply: str) -> None:
    assert is_affirmative(reply) is True


@pytest.mark.parametrize("reply", [
    "no", "No thanks", "nope", "nah", "cancel", "cancel it", "stop", "don't",
    "no, do it anyway", "", "   ",
])
def test_negatives_and_ambiguous_are_rejected(reply: str) -> None:
    assert is_affirmative(reply) is False


def test_new_request_instead_of_yes_no_is_rejected() -> None:
    # A user who types a fresh request instead of confirming must NOT trigger the
    # pending irreversible action.
    assert is_affirmative("what's on my calendar tomorrow?") is False
    assert is_affirmative("delete the meeting instead") is False


def test_leading_no_beats_later_affirmative_word() -> None:
    assert is_affirmative("no, yes I changed my mind cancel") is False
