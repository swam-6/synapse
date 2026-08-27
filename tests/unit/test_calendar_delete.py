"""Unit tests for delete_event.

Deletion is irreversible, so the safety properties matter more than the happy
path: the tool must never delete on an ambiguous or approximate match, and event
ids must never surface to the agent.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from synapse.errors import ExternalServiceError
from synapse.services.calendar.models import CalendarEvent
from synapse.tools.calendar import build_calendar_tools

IST = ZoneInfo("Asia/Kolkata")


class _FakeGateway:
    def __init__(self, events=None, *, list_error=None, delete_error=None):
        self._events = events or []
        self._list_error = list_error
        self._delete_error = delete_error
        self.deleted: list[str] = []

    async def list_events(self, *, time_min, time_max, max_results):
        if self._list_error:
            raise self._list_error
        self.window = (time_min, time_max)
        return self._events

    async def check_availability(self, *, time_min, time_max): return []
    async def create_event(self, **kw): raise AssertionError

    async def delete_event(self, *, event_id):
        if self._delete_error:
            raise self._delete_error
        self.deleted.append(event_id)


def _tool(gw):
    return {t.name: t for t in build_calendar_tools(gw, user_tz=IST)}["delete_event"]


def _event(eid, summary, start):
    return CalendarEvent(id=eid, summary=summary, start=start, end=start)


@pytest.mark.asyncio
async def test_deletes_the_single_match() -> None:
    gw = _FakeGateway([_event("abc123", "Scrum meeting", "2026-07-18T17:00:00+05:30")])
    result = await _tool(gw).ainvoke(
        {"summary": "Scrum meeting", "start": "2026-07-18T17:00:00+05:30"}
    )
    assert gw.deleted == ["abc123"]
    assert "Deleted 'Scrum meeting'" in result


@pytest.mark.asyncio
async def test_confirmation_never_exposes_the_event_id() -> None:
    gw = _FakeGateway([_event("52638oeb49etcp9canonbcghac", "Scrum", "2026-07-18T17:00:00+05:30")])
    result = await _tool(gw).ainvoke({"summary": "Scrum", "start": "2026-07-18T17:00:00+05:30"})
    assert "52638oeb49etcp9canonbcghac" not in result


@pytest.mark.asyncio
async def test_refuses_when_several_events_match() -> None:
    gw = _FakeGateway([
        _event("a", "Scrum meeting", "2026-07-18T16:00:00+05:30"),
        _event("b", "Scrum meeting", "2026-07-18T17:00:00+05:30"),
    ])
    # Date-only start: both same-titled events qualify -> must not guess.
    result = await _tool(gw).ainvoke({"summary": "Scrum meeting", "start": "2026-07-18"})
    assert gw.deleted == []
    assert "Found 2 events" in result and "which one" in result


@pytest.mark.asyncio
async def test_time_must_match_exactly() -> None:
    gw = _FakeGateway([_event("a", "Scrum meeting", "2026-07-18T16:00:00+05:30")])
    # Same title, different time -> refuse rather than delete the wrong event.
    result = await _tool(gw).ainvoke(
        {"summary": "Scrum meeting", "start": "2026-07-18T17:00:00+05:30"}
    )
    assert gw.deleted == []
    assert "No 'Scrum meeting' starts at" in result


@pytest.mark.asyncio
async def test_reports_when_nothing_matches() -> None:
    gw = _FakeGateway([_event("a", "Standup", "2026-07-18T09:00:00+05:30")])
    result = await _tool(gw).ainvoke({"summary": "Scrum", "start": "2026-07-18T17:00:00+05:30"})
    assert gw.deleted == []
    assert "No event matching 'Scrum'" in result


@pytest.mark.asyncio
async def test_naive_start_is_interpreted_in_user_timezone() -> None:
    # 17:00 naive must mean 17:00 IST, matching the stored +05:30 event.
    gw = _FakeGateway([_event("a", "Scrum", "2026-07-18T17:00:00+05:30")])
    await _tool(gw).ainvoke({"summary": "Scrum", "start": "2026-07-18T17:00:00"})
    assert gw.deleted == ["a"]


@pytest.mark.asyncio
async def test_invalid_date_is_rejected() -> None:
    gw = _FakeGateway()
    result = await _tool(gw).ainvoke({"summary": "X", "start": "next friday"})
    assert "Invalid date/time" in result
    assert gw.deleted == []


@pytest.mark.asyncio
async def test_lookup_failure_is_reported() -> None:
    gw = _FakeGateway(list_error=ExternalServiceError("calendar down"))
    result = await _tool(gw).ainvoke({"summary": "X", "start": "2026-07-18T17:00:00+05:30"})
    assert "Could not read the calendar" in result
    assert gw.deleted == []


@pytest.mark.asyncio
async def test_delete_failure_is_reported() -> None:
    gw = _FakeGateway(
        [_event("a", "Scrum", "2026-07-18T17:00:00+05:30")],
        delete_error=ExternalServiceError("permission denied"),
    )
    result = await _tool(gw).ainvoke({"summary": "Scrum", "start": "2026-07-18T17:00:00+05:30"})
    assert "Could not delete the event" in result and "permission denied" in result


def test_delete_event_is_approval_gated() -> None:
    """Irreversible actions must never run without explicit user confirmation."""
    from synapse.agents.calendar import build_calendar_worker_spec
    from synapse.config.settings import Settings

    spec = build_calendar_worker_spec(
        Settings(_env_file=None, require_approval_for_writes=True),  # type: ignore[call-arg]
        gateway=_FakeGateway(),
    )
    names = {t.name for t in spec.tools}
    assert "delete_event" in names
    # The gated tool is a wrapper, not the original function object.
    raw = {t.name for t in build_calendar_tools(_FakeGateway(), user_tz=IST)}
    assert names == raw  # same surface, wrapped underneath


def test_calendar_description_advertises_delete_to_manager() -> None:
    """The Manager routes by the worker's description; omitting 'delete' made it
    refuse delete requests even though the tool exists."""
    from synapse.prompts.calendar import CALENDAR_AGENT_DESCRIPTION

    assert "delete" in CALENDAR_AGENT_DESCRIPTION.lower()
