"""Human-readable rendering of calendar event spans.

Raw ISO timestamps were being read out to users. Times are now rendered in the
user's local timezone, while the exact ISO start is retained as a machine field
because ``delete_event`` needs it.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from synapse.services.calendar.models import CalendarEvent
from synapse.tools.calendar import _format_events, _humanise_span

IST = ZoneInfo("Asia/Kolkata")


def test_timed_event_same_day_reads_naturally() -> None:
    text = _humanise_span("2026-07-18T10:00:00+05:30", "2026-07-18T10:30:00+05:30", IST)
    assert text == "Sat 18 Jul 2026, 10:00 AM – 10:30 AM"


def test_times_are_converted_into_the_users_timezone() -> None:
    # 04:30 UTC is 10:00 IST — the user must see their own wall clock.
    text = _humanise_span("2026-07-18T04:30:00+00:00", "2026-07-18T05:00:00+00:00", IST)
    assert "10:00 AM" in text and "10:30 AM" in text


def test_single_all_day_event_is_not_reported_as_two_days() -> None:
    # Google reports all-day events with an EXCLUSIVE end date.
    text = _humanise_span("2026-07-17", "2026-07-18", IST)
    assert text == "Fri 17 Jul 2026 (all day)"


def test_multi_day_all_day_event_shows_true_last_day() -> None:
    text = _humanise_span("2026-07-17", "2026-07-20", IST)
    assert text == "Fri 17 Jul 2026 – Sun 19 Jul 2026 (all day)"


def test_event_crossing_midnight_shows_both_days() -> None:
    text = _humanise_span("2026-07-18T23:00:00+05:30", "2026-07-19T01:00:00+05:30", IST)
    assert "Sat 18 Jul 2026" in text and "Sun 19 Jul 2026" in text


def test_malformed_boundary_still_lists_the_event() -> None:
    # A formatting quirk must never make an event disappear.
    assert _humanise_span("not-a-date-T", "also-bad", IST) == "not-a-date-T → also-bad"


def test_format_events_is_readable_and_keeps_machine_start() -> None:
    events = [
        CalendarEvent(
            id="e1", summary="IEEE photo schedule",
            start="2026-07-18T10:00:00+05:30", end="2026-07-18T10:30:00+05:30",
            location="Lab",
        )
    ]
    text = _format_events(events, IST)
    assert "Sat 18 Jul 2026, 10:00 AM – 10:30 AM" in text
    assert "Lab" in text
    # Retained for delete_event, which needs the exact start.
    assert "start=2026-07-18T10:00:00+05:30" in text
    # The id stays hidden.
    assert "e1" not in text.replace("start=2026-07-18T10:00:00+05:30", "")


def test_empty_list_message_unchanged() -> None:
    assert _format_events([], IST) == "No events found in that time range."
