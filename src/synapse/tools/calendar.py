"""LangChain tools for the Calendar worker.

Thin, validated wrappers over the :class:`CalendarGateway`. Tools accept ISO 8601
timestamp strings, parse them into timezone-aware datetimes, and return
agent-readable text; on invalid input or a service failure they return a clear
message rather than raising, so the worker can reason about and report it.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from synapse.errors import ExternalServiceError
from synapse.observability.logging import get_logger
from synapse.services.calendar.models import BusyInterval, CalendarEvent
from synapse.services.calendar.protocols import CalendarGateway
from synapse.utils.datetime import parse_iso8601

logger = get_logger(__name__)


class CreateEventInput(BaseModel):
    """Validated arguments for creating a calendar event."""

    summary: str = Field(min_length=1, description="Event title.")
    start: str = Field(description="Start time as an ISO 8601 string.")
    end: str = Field(description="End time as an ISO 8601 string.")
    location: str | None = Field(default=None, description="Optional location.")
    description: str | None = Field(default=None, description="Optional details.")


class DeleteEventInput(BaseModel):
    """Validated arguments for deleting a calendar event.

    The event is identified by title and start time rather than by id: ids are
    deliberately never exposed to the agent, so it cannot read them out to the
    user or invent one.
    """

    summary: str = Field(min_length=1, description="Title of the event to delete.")
    start: str = Field(
        description="Start time of the event to delete, as an ISO 8601 string."
    )


def _is_all_day(value: str) -> bool:
    """Whether a Calendar boundary is a date (all-day event) rather than a datetime."""
    return "T" not in value


def _humanise_span(start: str, end: str, user_tz: tzinfo) -> str:
    """Render an event's start/end as readable local text.

    All-day events are reported by Google with an *exclusive* end date, so a
    single-day event arrives as ``2026-07-17 → 2026-07-18``; rendering that
    verbatim reads as a two-day meeting. Timed events are converted into the
    user's timezone so the text matches what they see in Google Calendar.
    """
    try:
        if _is_all_day(start):
            first = date.fromisoformat(start)
            # End is exclusive: subtract a day to get the true last day.
            last = date.fromisoformat(end) - timedelta(days=1) if _is_all_day(end) else first
            if last <= first:
                return f"{first.strftime('%a %d %b %Y')} (all day)"
            return (
                f"{first.strftime('%a %d %b %Y')} – {last.strftime('%a %d %b %Y')} (all day)"
            )

        start_dt = parse_iso8601(start, default_tz=user_tz).astimezone(user_tz)
        end_dt = parse_iso8601(end, default_tz=user_tz).astimezone(user_tz)
        day = start_dt.strftime("%a %d %b %Y")
        if start_dt.date() == end_dt.date():
            return f"{day}, {start_dt.strftime('%I:%M %p').lstrip('0')} – {end_dt.strftime('%I:%M %p').lstrip('0')}"
        return (
            f"{day} {start_dt.strftime('%I:%M %p').lstrip('0')} – "
            f"{end_dt.strftime('%a %d %b %Y')} {end_dt.strftime('%I:%M %p').lstrip('0')}"
        )
    except ValueError:
        return f"{start} → {end}"  # never lose the event over a formatting quirk


def _format_events(events: list[CalendarEvent], user_tz: tzinfo) -> str:
    """Render events for the agent to relay.

    The readable span is what the agent reports to the user. ``start=`` carries
    the exact ISO timestamp that ``delete_event`` needs — the agent uses it for
    tool calls only and is instructed not to repeat it to the user. The Calendar
    event id is deliberately omitted: no tool accepts one.
    """
    if not events:
        return "No events found in that time range."
    return "\n".join(
        f"{i}. {e.summary} | {_humanise_span(e.start, e.end, user_tz)}"
        + (f" | {e.location}" if e.location else "")
        + f" | start={e.start}"
        for i, e in enumerate(events, start=1)
    )


def _format_availability(
    intervals: list[BusyInterval], overlapping: list[CalendarEvent], user_tz: tzinfo
) -> str:
    """Describe availability from both free/busy blocks and overlapping events.

    Google's free/busy API omits events the user marked "Show as: Free" and ones
    they declined. Reporting free/busy alone therefore answers "is time blocked?"
    while the user asked "do I have anything on?" — and they would be told they
    are free during a meeting sitting in their calendar. Overlapping events are
    surfaced explicitly so the answer matches what the user can see.
    """
    if intervals:
        slots = "\n".join(
            f"- busy {_humanise_span(b.start, b.end, user_tz)}" for b in intervals
        )
        listed = ""
        if overlapping:
            listed = "\n" + "\n".join(
                f"- {e.summary}: {_humanise_span(e.start, e.end, user_tz)}"
                for e in overlapping
            )
        return f"Not free — that time is already blocked:\n{slots}{listed}"

    if overlapping:
        listed = "\n".join(
            f"- {e.summary}: {_humanise_span(e.start, e.end, user_tz)}"
            for e in overlapping
        )
        return (
            "Nothing is marked as busy, but these events overlap that time:\n"
            f"{listed}\n"
            "They are set to 'Free' in the calendar (or were declined), so they do "
            "not block the slot — mention them so the user can decide."
        )

    return "That time frame is completely free — no events and nothing blocked."


def build_calendar_tools(
    gateway: CalendarGateway,
    *,
    default_max_results: int = 10,
    user_tz: tzinfo = timezone.utc,
) -> list[BaseTool]:
    """Build the Calendar worker's tools bound to ``gateway``.

    Args:
        gateway: The calendar service.
        default_max_results: Baseline result cap.
        user_tz: The user's timezone. Timestamps supplied without an explicit
            offset are interpreted in it, and it is what ``get_current_datetime``
            reports, so wall-clock requests land at the intended local time.
    """

    @tool
    async def get_current_datetime() -> str:
        """Return the current local date/time plus the resolved relative dates.

        Call this first whenever the request involves a relative date or time
        (today, tomorrow, yesterday, this week, "in 2 hours"). Use the dates it
        reports verbatim — they are already calculated, so you must not do any
        date arithmetic yourself.
        """
        now = datetime.now(user_tz)
        offset = now.strftime("%z")
        offset = f"{offset[:3]}:{offset[3:]}"  # +0530 -> +05:30

        def day(d: datetime) -> str:
            return f"{d.strftime('%A')} {d.date().isoformat()}"

        # Relative dates are precomputed: models routinely get this arithmetic
        # wrong (reporting today's date as "tomorrow"), and a wrong date silently
        # creates the event on the wrong day.
        return (
            f"Current local time: {now.strftime('%Y-%m-%dT%H:%M:%S')}{offset} "
            f"({now.tzname()}, UTC{offset}).\n"
            f"TODAY is {day(now)}.\n"
            f"TOMORROW is {day(now + timedelta(days=1))}.\n"
            f"YESTERDAY was {day(now - timedelta(days=1))}.\n"
            f"Use these dates exactly as given. Always append the offset "
            f"{offset} to timestamps you send to other tools."
        )

    @tool
    async def list_events(
        time_min: str | None = None, time_max: str | None = None, max_results: int = 10
    ) -> str:
        """List calendar events in a time range.

        ``time_min``/``time_max`` are ISO 8601 strings; if ``time_min`` is
        omitted the current time is used. Returns upcoming events when
        ``time_max`` is omitted.
        """
        try:
            start = parse_iso8601(time_min, default_tz=user_tz) if time_min else datetime.now(user_tz)
            end = parse_iso8601(time_max, default_tz=user_tz) if time_max else None
        except ValueError as exc:
            return f"Invalid date/time: {exc}. Use ISO 8601, e.g. 2026-07-20T09:00:00Z."
        capped = max(1, min(max_results, default_max_results * 5))
        try:
            events = await gateway.list_events(time_min=start, time_max=end, max_results=capped)
        except ExternalServiceError as exc:
            logger.warning("tool_list_events_failed", error=str(exc))
            return f"Could not read the calendar: {exc}"
        return _format_events(events, user_tz)

    @tool
    async def check_availability(time_min: str, time_max: str) -> str:
        """Check whether a time frame is free, or list conflicting busy intervals.

        Both bounds are ISO 8601 strings.
        """
        try:
            start = parse_iso8601(time_min, default_tz=user_tz)
            end = parse_iso8601(time_max, default_tz=user_tz)
        except ValueError as exc:
            return f"Invalid date/time: {exc}. Use ISO 8601, e.g. 2026-07-20T09:00:00Z."
        if end <= start:
            return "The end time must be after the start time."
        try:
            busy = await gateway.check_availability(time_min=start, time_max=end)
            # Free/busy alone misses events shown as "Free" or declined, so the
            # window's actual events are checked too.
            overlapping = await gateway.list_events(
                time_min=start, time_max=end, max_results=50
            )
        except ExternalServiceError as exc:
            logger.warning("tool_check_availability_failed", error=str(exc))
            return f"Could not check availability: {exc}"
        return _format_availability(busy, overlapping, user_tz)

    @tool(args_schema=CreateEventInput)
    async def create_event(
        summary: str,
        start: str,
        end: str,
        location: str | None = None,
        description: str | None = None,
    ) -> str:
        """Create a calendar event. Start and end are ISO 8601 strings."""
        try:
            start_dt = parse_iso8601(start, default_tz=user_tz)
            end_dt = parse_iso8601(end, default_tz=user_tz)
        except ValueError as exc:
            return f"Invalid date/time: {exc}. Use ISO 8601, e.g. 2026-07-20T09:00:00Z."
        if end_dt <= start_dt:
            return "The end time must be after the start time."
        if end_dt - start_dt > timedelta(days=365):
            return "That event span looks too long (over a year); please check the dates."
        try:
            event = await gateway.create_event(
                summary=summary, start=start_dt, end=end_dt,
                location=location, description=description,
            )
        except ExternalServiceError as exc:
            logger.warning("tool_create_event_failed", error=str(exc))
            return f"Could not create the event: {exc}"
        link = f" ({event.html_link})" if event.html_link else ""
        return f"Created event '{event.summary}' from {event.start} to {event.end}{link}."

    @tool(args_schema=DeleteEventInput)
    async def delete_event(summary: str, start: str) -> str:
        """Delete a calendar event, identified by its title and start time.

        Deletion is permanent. The event is located by searching the day of
        ``start``; the request is refused rather than guessed if the title and
        time do not identify exactly one event.
        """
        try:
            target = parse_iso8601(start, default_tz=user_tz)
        except ValueError as exc:
            return f"Invalid date/time: {exc}. Use ISO 8601, e.g. 2026-07-18T17:00:00+05:30."

        # Search the whole local day containing the requested start.
        local = target.astimezone(user_tz)
        day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        try:
            events = await gateway.list_events(
                time_min=day_start, time_max=day_end, max_results=50
            )
        except ExternalServiceError as exc:
            logger.warning("tool_delete_event_lookup_failed", error=str(exc))
            return f"Could not read the calendar: {exc}"

        wanted = summary.strip().lower()
        matches = [e for e in events if wanted in e.summary.strip().lower()]
        day = day_start.date().isoformat()

        # When a specific time was given, it must match — never delete a
        # same-titled event at a different time.
        if "T" in start:
            exact = []
            for event in matches:
                try:
                    if parse_iso8601(event.start, default_tz=user_tz) == target:
                        exact.append(event)
                except ValueError:
                    continue
            if not exact:
                if matches:
                    listed = "; ".join(f"'{e.summary}' at {e.start}" for e in matches)
                    return (
                        f"No '{summary}' starts at {start}. On {day} I found: {listed}. "
                        f"Ask the user which one they mean, then retry with its exact start time."
                    )
                return f"No event matching '{summary}' was found on {day}."
            matches = exact

        if not matches:
            return f"No event matching '{summary}' was found on {day}."
        if len(matches) > 1:
            listed = "; ".join(f"'{e.summary}' at {e.start}" for e in matches)
            return (
                f"Found {len(matches)} events matching '{summary}' on {day}: {listed}. "
                f"Ask the user which one to delete, then retry with its exact start time."
            )

        victim = matches[0]
        try:
            await gateway.delete_event(event_id=victim.id)
        except ExternalServiceError as exc:
            logger.warning("tool_delete_event_failed", error=str(exc))
            return f"Could not delete the event: {exc}"
        return f"Deleted '{victim.summary}' which was scheduled for {victim.start}."

    return [get_current_datetime, list_events, check_availability, create_event, delete_event]
