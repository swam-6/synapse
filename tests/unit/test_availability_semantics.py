"""Availability must reflect what the user can see in their calendar.

Real bug: asked "am I free at 10:15?" during a 10:00-10:30 event, the bot said
yes. Google's free/busy API omits events marked "Show as: Free" (and declined
ones), so free/busy alone answers "is time blocked?" — not the user's actual
question, "do I have anything on?".
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from synapse.services.calendar.models import BusyInterval, CalendarEvent
from synapse.tools.calendar import build_calendar_tools

IST = ZoneInfo("Asia/Kolkata")

_IEEE = CalendarEvent(
    id="e1", summary="IEEE photo schedule",
    start="2026-07-18T10:00:00+05:30", end="2026-07-18T10:30:00+05:30",
)


class _Gw:
    def __init__(self, busy=None, events=None):
        self._busy = busy or []
        self._events = events or []

    async def check_availability(self, *, time_min, time_max):
        return self._busy

    async def list_events(self, *, time_min, time_max, max_results):
        return self._events

    async def create_event(self, **k): raise AssertionError
    async def delete_event(self, **k): raise AssertionError


def _tool(gw):
    return {t.name: t for t in build_calendar_tools(gw, user_tz=IST)}["check_availability"]


@pytest.mark.asyncio
async def test_event_shown_as_free_is_still_surfaced() -> None:
    """The exact failure: Google says not-busy, but an event overlaps."""
    gw = _Gw(busy=[], events=[_IEEE])
    result = await _tool(gw).ainvoke(
        {"time_min": "2026-07-18T10:15:00+05:30", "time_max": "2026-07-18T10:30:00+05:30"}
    )
    assert "IEEE photo schedule" in result
    assert "overlap" in result.lower()
    # Must not claim the slot is simply free.
    assert "completely free" not in result.lower()


@pytest.mark.asyncio
async def test_truly_empty_slot_is_reported_free() -> None:
    result = await _tool(_Gw(busy=[], events=[])).ainvoke(
        {"time_min": "2026-07-18T14:00:00+05:30", "time_max": "2026-07-18T15:00:00+05:30"}
    )
    assert "completely free" in result.lower()


@pytest.mark.asyncio
async def test_blocked_slot_reports_conflict_and_names_the_event() -> None:
    gw = _Gw(
        busy=[BusyInterval(start="2026-07-18T16:00:00+05:30", end="2026-07-18T16:30:00+05:30")],
        events=[CalendarEvent(id="e2", summary="Scrum meeting",
                              start="2026-07-18T16:00:00+05:30",
                              end="2026-07-18T16:30:00+05:30")],
    )
    result = await _tool(gw).ainvoke(
        {"time_min": "2026-07-18T16:00:00+05:30", "time_max": "2026-07-18T16:30:00+05:30"}
    )
    assert "not free" in result.lower()
    assert "Scrum meeting" in result


@pytest.mark.asyncio
async def test_availability_times_are_human_readable() -> None:
    gw = _Gw(busy=[], events=[_IEEE])
    result = await _tool(gw).ainvoke(
        {"time_min": "2026-07-18T10:15:00+05:30", "time_max": "2026-07-18T10:30:00+05:30"}
    )
    assert "10:00 AM" in result
    assert "2026-07-18T10:00:00+05:30" not in result
