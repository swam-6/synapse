"""Unit tests for the Calendar worker tools using a fake gateway."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from synapse.errors import ExternalServiceError
from synapse.services.calendar.models import BusyInterval, CalendarEvent
from synapse.tools.calendar import build_calendar_tools


class _FakeGateway:
    def __init__(self, *, events=None, busy=None, created=None, error=None):
        self._events = events or []
        self._busy = busy or []
        self._created = created
        self._error = error
        self.create_calls: list[dict] = []

    async def list_events(self, *, time_min, time_max, max_results):
        if self._error:
            raise self._error
        return self._events

    async def check_availability(self, *, time_min, time_max):
        if self._error:
            raise self._error
        return self._busy

    async def create_event(self, *, summary, start, end, location=None, description=None):
        if self._error:
            raise self._error
        self.create_calls.append(
            {"summary": summary, "start": start, "end": end, "location": location}
        )
        return self._created


def _tools(gateway) -> dict:
    return {t.name: t for t in build_calendar_tools(gateway)}


@pytest.mark.asyncio
async def test_list_events_formats() -> None:
    gw = _FakeGateway(
        events=[
            CalendarEvent(
                id="e1", summary="Standup", start="2026-07-20T09:00:00Z",
                end="2026-07-20T09:15:00Z", location="Zoom",
            )
        ]
    )
    result = await _tools(gw)["list_events"].ainvoke({})
    assert "Standup" in result and "Zoom" in result
    assert "2026-07-20T09:00:00Z" in result


@pytest.mark.asyncio
async def test_list_events_does_not_leak_internal_ids() -> None:
    """No tool accepts an event id, so surfacing it only clutters the reply."""
    gw = _FakeGateway(
        events=[
            CalendarEvent(
                id="52638oeb49etcp9canonbcghac", summary="IEEE photo",
                start="2026-07-18T10:00:00+05:30", end="2026-07-18T10:30:00+05:30",
            )
        ]
    )
    result = await _tools(gw)["list_events"].ainvoke({})
    assert "IEEE photo" in result
    assert "52638oeb49etcp9canonbcghac" not in result
    assert "id=" not in result


@pytest.mark.asyncio
async def test_list_events_invalid_date() -> None:
    result = await _tools(_FakeGateway())["list_events"].ainvoke({"time_min": "yesterday"})
    assert "Invalid date/time" in result


@pytest.mark.asyncio
async def test_check_availability_free() -> None:
    result = await _tools(_FakeGateway(busy=[]))["check_availability"].ainvoke(
        {"time_min": "2026-07-20T09:00:00Z", "time_max": "2026-07-20T10:00:00Z"}
    )
    assert "completely free" in result


@pytest.mark.asyncio
async def test_check_availability_busy() -> None:
    gw = _FakeGateway(
        busy=[BusyInterval(start="2026-07-20T09:30:00Z", end="2026-07-20T10:00:00Z")]
    )
    result = await _tools(gw)["check_availability"].ainvoke(
        {"time_min": "2026-07-20T09:00:00Z", "time_max": "2026-07-20T10:00:00Z"}
    )
    assert "not free" in result.lower()
    assert "9:30 AM" in result or "09:30" in result


@pytest.mark.asyncio
async def test_check_availability_rejects_bad_window() -> None:
    result = await _tools(_FakeGateway())["check_availability"].ainvoke(
        {"time_min": "2026-07-20T10:00:00Z", "time_max": "2026-07-20T09:00:00Z"}
    )
    assert "end time must be after" in result


@pytest.mark.asyncio
async def test_create_event_confirms_and_calls_gateway() -> None:
    gw = _FakeGateway(
        created=CalendarEvent(
            id="e9", summary="Lunch", start="2026-07-20T12:00:00+00:00",
            end="2026-07-20T13:00:00+00:00", html_link="http://cal/e9",
        )
    )
    result = await _tools(gw)["create_event"].ainvoke(
        {"summary": "Lunch", "start": "2026-07-20T12:00:00Z", "end": "2026-07-20T13:00:00Z"}
    )
    assert "Created event 'Lunch'" in result and "http://cal/e9" in result
    assert len(gw.create_calls) == 1
    assert isinstance(gw.create_calls[0]["start"], datetime)


@pytest.mark.asyncio
async def test_create_event_rejects_inverted_times() -> None:
    gw = _FakeGateway()
    result = await _tools(gw)["create_event"].ainvoke(
        {"summary": "X", "start": "2026-07-20T13:00:00Z", "end": "2026-07-20T12:00:00Z"}
    )
    assert "end time must be after" in result
    assert gw.create_calls == []


@pytest.mark.asyncio
async def test_list_events_reports_service_error() -> None:
    gw = _FakeGateway(error=ExternalServiceError("calendar down"))
    result = await _tools(gw)["list_events"].ainvoke({})
    assert "Could not read the calendar" in result and "calendar down" in result


class _RecordingGateway(_FakeGateway):
    """Captures the window ``list_events`` was actually called with."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.windows: list[tuple] = []

    async def list_events(self, *, time_min, time_max, max_results):
        self.windows.append((time_min, time_max))
        return await super().list_events(
            time_min=time_min, time_max=time_max, max_results=max_results
        )


@pytest.mark.asyncio
async def test_period_today_covers_the_whole_local_day() -> None:
    """A named period is resolved server-side, so the agent does no date maths.

    Models got this wrong often enough to matter: asked at 6pm, an agent-built
    window started at "now" and silently hid that morning's events.
    """
    gw = _RecordingGateway()
    await _tools(gw)["list_events"].ainvoke({"period": "today"})

    start, end = gw.windows[0]
    today = datetime.now(timezone.utc).date()
    assert start.date() == today and (start.hour, start.minute) == (0, 0)
    assert end.date() == today and (end.hour, end.minute) == (23, 59)


@pytest.mark.asyncio
async def test_period_this_week_spans_seven_days_from_today() -> None:
    gw = _RecordingGateway()
    await _tools(gw)["list_events"].ainvoke({"period": "this_week"})

    start, end = gw.windows[0]
    assert start.date() == datetime.now(timezone.utc).date()
    assert (end.date() - start.date()).days == 6  # seven days inclusive


@pytest.mark.asyncio
async def test_period_accepts_spaced_and_cased_names() -> None:
    gw = _RecordingGateway()
    await _tools(gw)["list_events"].ainvoke({"period": "This Week"})
    assert gw.windows, "a spaced/cased period name should still resolve"


@pytest.mark.asyncio
async def test_unknown_period_lists_choices_and_skips_the_api() -> None:
    gw = _RecordingGateway()
    result = await _tools(gw)["list_events"].ainvoke({"period": "next fortnight"})

    assert "this_week" in result  # the valid choices are offered
    assert gw.windows == [], "an unresolved period must not query the calendar"
