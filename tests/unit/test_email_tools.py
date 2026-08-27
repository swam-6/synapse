"""Unit tests for the Email worker tools using fake services."""

from __future__ import annotations

import pytest

from synapse.errors import ExternalServiceError
from synapse.services.email.models import Contact, EmailMessage, EmailSummary
from synapse.tools.email import build_email_tools


class _FakeReader:
    def __init__(self, summaries=None, message=None, error=None):
        self._summaries = summaries or []
        self._message = message
        self._error = error

    async def list_recent(self, max_results: int):
        if self._error:
            raise self._error
        return self._summaries[:max_results]

    async def get_message(self, message_id: str):
        if self._error:
            raise self._error
        return self._message


class _FakeSender:
    def __init__(self, error=None):
        self.sent: list[dict] = []
        self._error = error

    async def send(self, *, to: str, subject: str, body: str) -> None:
        if self._error:
            raise self._error
        self.sent.append({"to": to, "subject": subject, "body": body})


class _FakeResolver:
    def __init__(self, contacts=None, error=None):
        self._contacts = contacts or []
        self._error = error

    async def resolve(self, name: str):
        if self._error:
            raise self._error
        return self._contacts


def _tools(reader=None, sender=None, resolver=None) -> dict:
    tools = build_email_tools(
        reader or _FakeReader(), sender or _FakeSender(), resolver or _FakeResolver()
    )
    return {t.name: t for t in tools}


@pytest.mark.asyncio
async def test_list_recent_emails_formats_summaries() -> None:
    reader = _FakeReader(
        summaries=[
            EmailSummary(id="a1", sender="Bob <bob@x.com>", subject="Hi", date="Mon", snippet="hello")
        ]
    )
    result = await _tools(reader=reader)["list_recent_emails"].ainvoke({"max_results": 5})
    assert "id=a1" in result and "Bob <bob@x.com>" in result and "hello" in result


@pytest.mark.asyncio
async def test_list_recent_emails_empty() -> None:
    result = await _tools()["list_recent_emails"].ainvoke({"max_results": 5})
    assert "no recent messages" in result.lower()


@pytest.mark.asyncio
async def test_get_email_returns_body() -> None:
    reader = _FakeReader(
        message=EmailMessage(
            id="a1", sender="bob@x.com", subject="Hi", date="Mon", snippet="s", body="Full body here."
        )
    )
    result = await _tools(reader=reader)["get_email"].ainvoke({"message_id": "a1"})
    assert "Full body here." in result and "Subject: Hi" in result


@pytest.mark.asyncio
async def test_send_email_rejects_non_address() -> None:
    sender = _FakeSender()
    result = await _tools(sender=sender)["send_email"].ainvoke(
        {"to": "Alice", "subject": "Hi", "body": "Hello"}
    )
    assert "not a valid email address" in result
    assert sender.sent == []  # nothing was sent


@pytest.mark.asyncio
async def test_send_email_sends_to_valid_address() -> None:
    sender = _FakeSender()
    result = await _tools(sender=sender)["send_email"].ainvoke(
        {"to": "alice@example.com", "subject": "Hi", "body": "Hello"}
    )
    assert "Email sent to alice@example.com" in result
    assert sender.sent == [{"to": "alice@example.com", "subject": "Hi", "body": "Hello"}]


@pytest.mark.asyncio
async def test_send_email_reports_service_failure() -> None:
    sender = _FakeSender(error=ExternalServiceError("SMTP down"))
    result = await _tools(sender=sender)["send_email"].ainvoke(
        {"to": "alice@example.com", "subject": "Hi", "body": "Hello"}
    )
    assert "Could not send the email" in result and "SMTP down" in result


@pytest.mark.asyncio
async def test_resolve_contact_lists_matches() -> None:
    resolver = _FakeResolver(contacts=[Contact(name="Alice", email="alice@example.com")])
    result = await _tools(resolver=resolver)["resolve_contact"].ainvoke({"name": "Alice"})
    assert "Alice: alice@example.com" in result


@pytest.mark.asyncio
async def test_resolve_contact_no_match() -> None:
    result = await _tools()["resolve_contact"].ainvoke({"name": "Nobody"})
    assert "No contacts found" in result
