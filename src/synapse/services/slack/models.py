"""Typed shapes returned by the Slack service."""

from __future__ import annotations

from pydantic import BaseModel


class SlackChannel(BaseModel):
    """A Slack conversation the bot can access."""

    id: str
    name: str


class SlackMessage(BaseModel):
    """A single Slack message. ``user`` is the author's Slack id; ``ts`` its timestamp."""

    user: str
    text: str
    ts: str
