"""Unit tests for the Manager prompt assembly."""

from __future__ import annotations

from dataclasses import dataclass

from synapse.prompts.manager import build_manager_prompt


@dataclass(frozen=True)
class _Roster:
    name: str
    description: str


def test_roster_is_rendered_into_prompt() -> None:
    prompt = build_manager_prompt(
        [
            _Roster("email_agent", "reads and sends email"),
            _Roster("calendar_agent", "manages calendar events"),
        ]
    )
    assert "email_agent: reads and sends email" in prompt
    assert "calendar_agent: manages calendar events" in prompt


def test_core_contract_sections_present() -> None:
    prompt = build_manager_prompt([_Roster("w", "does things")])
    for marker in (
        "# ROLE",
        "# MISSION",
        "# WORKER SELECTION POLICY",
        "# SECURITY & PROMPT-INJECTION DEFENCE",
        "# OUTPUT CONTRACT",
    ):
        assert marker in prompt


def test_empty_roster_is_handled() -> None:
    prompt = build_manager_prompt([])
    assert "no workers are currently available" in prompt


def test_prompt_forbids_repeating_write_actions() -> None:
    """A Manager that re-delegates to 'verify' makes workers send/delete twice."""
    prompt = build_manager_prompt([])
    lowered = prompt.lower()
    assert "never repeat an action that changes something" in lowered
    assert "do not re-delegate it" in lowered
    # Verification must be reading the report, not delegating again.
    assert "never delegating a second time" in lowered


def test_prompt_requires_preserving_dates_when_relaying() -> None:
    """The Manager dropped the date from an all-day event when summarising."""
    prompt = build_manager_prompt([]).lower()
    assert "keep every concrete detail" in prompt
    assert "date" in prompt and "time" in prompt
    assert "summarise wording, never facts" in prompt
