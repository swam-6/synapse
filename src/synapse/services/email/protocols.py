"""Capability interfaces for the email integration (Dependency Inversion).

Tools depend on these narrow Protocols, not on the concrete Gmail/SMTP/People
service classes. Production wires the real services; tests supply fakes. This
keeps the tool layer free of any vendor SDK and trivially unit-testable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from synapse.services.email.models import Contact, EmailMessage, EmailSummary


@runtime_checkable
class MailReader(Protocol):
    """Reads inbox mail."""

    async def list_recent(self, max_results: int) -> list[EmailSummary]:
        """Return the most recent inbox messages as summaries."""
        ...

    async def get_message(self, message_id: str) -> EmailMessage:
        """Return one full message, including its body, by id."""
        ...


@runtime_checkable
class MailSender(Protocol):
    """Sends mail on the user's behalf."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        """Send an email to ``to`` with ``subject`` and ``body``."""
        ...


@runtime_checkable
class ContactResolver(Protocol):
    """Resolves a person's name to candidate email addresses."""

    async def resolve(self, name: str) -> list[Contact]:
        """Return contacts whose name matches ``name``."""
        ...
