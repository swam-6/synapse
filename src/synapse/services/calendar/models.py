"""Typed data shapes returned by the calendar service."""

from __future__ import annotations

from pydantic import BaseModel


class CalendarEvent(BaseModel):
    """A calendar event. ``start``/``end`` are ISO 8601 strings (date or datetime)."""

    id: str
    summary: str
    start: str
    end: str
    location: str | None = None
    html_link: str | None = None


class BusyInterval(BaseModel):
    """A busy time span from a free/busy query (ISO 8601 boundaries)."""

    start: str
    end: str
