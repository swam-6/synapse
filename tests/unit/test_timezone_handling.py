"""Timezone correctness for calendar times.

Regression guard for a real bug: an agent asked for "4pm tomorrow" emits a naive
wall-clock time meaning the user's local 4pm. Defaulting that to UTC stored the
event shifted by the user's offset (a +05:30 user saw 9:30pm instead of 4pm).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from synapse.config.settings import Settings
from synapse.services.calendar.models import CalendarEvent
from synapse.tools.calendar import build_calendar_tools
from synapse.utils.datetime import parse_iso8601

IST = ZoneInfo("Asia/Kolkata")


def test_naive_time_uses_supplied_timezone_not_utc() -> None:
    parsed = parse_iso8601("2026-07-18T16:00:00", default_tz=IST)
    assert parsed.utcoffset().total_seconds() == 5.5 * 3600
    # The intended moment: 4pm IST == 10:30 UTC (NOT 16:00 UTC).
    assert parsed.astimezone(timezone.utc).hour == 10
    assert parsed.astimezone(timezone.utc).minute == 30


def test_explicit_offset_is_always_honoured() -> None:
    # An explicit offset must win over the default.
    parsed = parse_iso8601("2026-07-18T16:00:00Z", default_tz=IST)
    assert parsed.utcoffset().total_seconds() == 0


def test_default_remains_utc_when_unspecified() -> None:
    assert parse_iso8601("2026-07-18T16:00:00").tzinfo == timezone.utc


class _CapturingGateway:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def list_events(self, *, time_min, time_max, max_results): return []
    async def check_availability(self, *, time_min, time_max): return []

    async def create_event(self, *, summary, start, end, location=None, description=None):
        self.created.append({"start": start, "end": end})
        return CalendarEvent(id="e1", summary=summary, start=start.isoformat(), end=end.isoformat())


@pytest.mark.asyncio
async def test_create_event_interprets_naive_time_as_user_local() -> None:
    gw = _CapturingGateway()
    tools = {t.name: t for t in build_calendar_tools(gw, user_tz=IST)}

    await tools["create_event"].ainvoke(
        {"summary": "Scrum", "start": "2026-07-18T16:00:00", "end": "2026-07-18T16:30:00"}
    )

    start = gw.created[0]["start"]
    # Must be 4pm IST, i.e. 10:30 UTC — the exact bug that shifted it to 9:30pm.
    assert start.astimezone(IST).hour == 16
    assert start.astimezone(timezone.utc).hour == 10


@pytest.mark.asyncio
async def test_get_current_datetime_reports_user_timezone() -> None:
    tools = {t.name: t for t in build_calendar_tools(_CapturingGateway(), user_tz=IST)}
    result = await tools["get_current_datetime"].ainvoke({})
    # Agents need the offset to build correct timestamps.
    assert "+05:30" in result
    assert "TODAY is" in result


def test_settings_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="Unknown timezone"):
        Settings(_env_file=None, timezone="Mars/Olympus")  # type: ignore[call-arg]


def test_settings_tzinfo_resolves() -> None:
    s = Settings(_env_file=None, timezone="Asia/Kolkata")  # type: ignore[call-arg]
    assert datetime(2026, 7, 18, tzinfo=s.tzinfo()).utcoffset().total_seconds() == 5.5 * 3600


@pytest.mark.asyncio
async def test_get_current_datetime_precomputes_relative_dates() -> None:
    """The model must never do date arithmetic: it reported today as 'tomorrow'."""
    from datetime import timedelta

    tools = {t.name: t for t in build_calendar_tools(_CapturingGateway(), user_tz=IST)}
    result = await tools["get_current_datetime"].ainvoke({})

    now = datetime.now(IST)
    today = now.date().isoformat()
    tomorrow = (now + timedelta(days=1)).date().isoformat()
    yesterday = (now - timedelta(days=1)).date().isoformat()

    assert f"TODAY is {now.strftime('%A')} {today}" in result
    assert f"TOMORROW is {(now + timedelta(days=1)).strftime('%A')} {tomorrow}" in result
    assert f"YESTERDAY was {(now - timedelta(days=1)).strftime('%A')} {yesterday}" in result
    # Tomorrow must be a genuinely different date from today.
    assert today != tomorrow
    # The offset must be given in a form usable directly in a timestamp.
    assert "+05:30" in result
