"""Typed data shapes returned by the email services.

Services return these validated models rather than raw provider dicts, so tools
and agents work against a stable, documented contract independent of the Gmail /
People payload formats.
"""

from __future__ import annotations

from pydantic import BaseModel


class EmailSummary(BaseModel):
    """A lightweight inbox entry (headers + snippet, no full body)."""

    id: str
    sender: str
    subject: str
    date: str
    snippet: str


class EmailMessage(EmailSummary):
    """A full email message, including its plain-text body."""

    body: str


class Contact(BaseModel):
    """A resolved contact: a display name mapped to an email address."""

    name: str
    email: str
