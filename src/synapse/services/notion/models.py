"""Typed shapes and the exact Notion to-do schema Synapse depends on.

The property names and status option values below MUST match the user-designed
Notion database verbatim — Notion property access is name- and value-sensitive.
Centralising them here guarantees every read and write uses the same literals.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

# --- Exact Notion property names (must match the database) -------------------
TITLE_PROPERTY = "Title"
STATUS_PROPERTY = "Status"
DATE_PROPERTY = "Date"


class NotionStatus(str, Enum):
    """The exact allowed values of the ``Status`` property."""

    NOT_STARTED = "Not started"
    IN_PROGRESS = "In progress"
    DONE = "Done"


#: New tasks default to this status per the schema.
DEFAULT_STATUS = NotionStatus.NOT_STARTED

#: The canonical set of acceptable status strings, for input validation.
ALLOWED_STATUSES: tuple[str, ...] = tuple(status.value for status in NotionStatus)


class NotionTask(BaseModel):
    """A to-do item read from or written to the Notion database.

    ``due_date`` is the ISO 8601 string from the ``Date`` property (date or
    datetime), or ``None`` when unset.
    """

    id: str
    title: str
    status: str | None = None
    due_date: str | None = None
    url: str | None = None
