"""Capability interface for the calendar integration (Dependency Inversion).

Calendar tools depend on this Protocol, not on the concrete Google Calendar
service, keeping the tool layer SDK-free and unit-testable with fakes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from synapse.services.calendar.models import BusyInterval, CalendarEvent


@runtime_checkable
class CalendarGateway(Protocol):
    """Reads and creates calendar events, and checks availability."""

    async def list_events(
        self, *, time_min: datetime, time_max: datetime | None, max_results: int
    ) -> list[CalendarEvent]:
        """Return events between ``time_min`` and ``time_max`` (or upcoming)."""
        ...

    async def check_availability(
        self, *, time_min: datetime, time_max: datetime
    ) -> list[BusyInterval]:
        """Return busy intervals within the window (empty means fully free)."""
        ...

    async def create_event(
        self,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        location: str | None = None,
        description: str | None = None,
    ) -> CalendarEvent:
        """Create an event and return it as stored (with id and link)."""
        ...

    async def delete_event(self, *, event_id: str) -> None:
        """Permanently delete the event with ``event_id``."""
        ...
