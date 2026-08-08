"""LangChain tools for the Email worker.

Each tool is a thin, validated wrapper over an email service capability
(``MailReader`` / ``MailSender`` / ``ContactResolver``). Tools own input schemas,
input validation, error handling, and logging — never orchestration. On a service
failure a tool returns a clear, agent-readable message instead of raising, so the
worker can reason about the failure and report it rather than crashing.

``build_email_tools`` binds concrete services into the tool closures, so the tools
carry no global state and are trivially testable with fake services.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from synapse.errors import ExternalServiceError
from synapse.observability.logging import get_logger
from synapse.services.email.protocols import ContactResolver, MailReader, MailSender
from synapse.utils.validation import is_probably_email

logger = get_logger(__name__)


class SendEmailInput(BaseModel):
    """Validated arguments for sending an email."""

    to: str = Field(description="Recipient email address (must be a valid address).")
    subject: str = Field(min_length=1, description="The email subject line.")
    body: str = Field(min_length=1, description="The plain-text email body.")


def _format_summaries(summaries: list, empty_message: str) -> str:
    """Render a list of email summaries as a compact, numbered text block."""
    if not summaries:
        return empty_message
    lines = []
    for index, item in enumerate(summaries, start=1):
        lines.append(
            f"{index}. id={item.id} | From: {item.sender} | Subject: {item.subject}"
            f" | {item.date}\n   {item.snippet}"
        )
    return "\n".join(lines)


def build_email_tools(
    reader: MailReader, sender: MailSender, resolver: ContactResolver
) -> list[BaseTool]:
    """Build the Email worker's tools bound to the given services.

    Args:
        reader: Inbox reader (Gmail).
        sender: Outbound sender (SMTP).
        resolver: Contact resolver (People).

    Returns:
        The list of tools to register with the Email worker agent.
    """

    @tool
    async def list_recent_emails(max_results: int = 5) -> str:
        """List the most recent inbox emails as id/sender/subject/snippet summaries.

        Use this to see what is in the inbox before reading or summarising. Pass
        ``max_results`` (1-25) to control how many are returned.
        """
        capped = max(1, min(max_results, 25))
        try:
            summaries = await reader.list_recent(capped)
        except ExternalServiceError as exc:
            logger.warning("tool_list_recent_emails_failed", error=str(exc))
            return f"Could not read the inbox: {exc}"
        return _format_summaries(summaries, "The inbox has no recent messages.")

    @tool
    async def get_email(message_id: str) -> str:
        """Fetch one full email (headers and body) by its message id.

        Use after ``list_recent_emails`` to read or summarise a specific message.
        """
        try:
            message = await reader.get_message(message_id)
        except ExternalServiceError as exc:
            logger.warning("tool_get_email_failed", error=str(exc))
            return f"Could not read message {message_id!r}: {exc}"
        
        MAX_BODY_CHARS = 4000

        body = message.body

        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS] + "\n\n...[email truncated]"

        return (
            f"From: {message.sender}\n"
            f"Subject: {message.subject}\n"
            f"Date: {message.date}\n\n"
            f"{body}"
        )

    @tool(args_schema=SendEmailInput)
    async def send_email(to: str, subject: str, body: str) -> str:
        """Send an email to a single recipient address.

        The recipient must be a valid email address; if you only have a name,
        resolve it with ``resolve_contact`` first.
        """
        if not is_probably_email(to):
            return (
                f"{to!r} is not a valid email address. Use resolve_contact to find "
                f"the address first."
            )
        try:
            await sender.send(to=to, subject=subject, body=body)
        except ExternalServiceError as exc:
            logger.warning("tool_send_email_failed", error=str(exc))
            return f"Could not send the email: {exc}"
        return f"Email sent to {to} with subject {subject!r}."

    @tool
    async def resolve_contact(name: str) -> str:
        """Resolve a person's name to candidate email addresses from contacts.

        Use before sending when the user names a recipient instead of giving an
        address.
        """
        try:
            contacts = await resolver.resolve(name)
        except ExternalServiceError as exc:
            logger.warning("tool_resolve_contact_failed", error=str(exc))
            return f"Could not look up {name!r}: {exc}"
        if not contacts:
            return f"No contacts found matching {name!r}."
        return "\n".join(f"{c.name}: {c.email}" for c in contacts)

    return [list_recent_emails, get_email, send_email, resolve_contact]
