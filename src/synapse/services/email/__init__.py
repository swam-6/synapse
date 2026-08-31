"""Email integration: Gmail (read), SMTP-over-SSL (send), People (contacts)."""

from synapse.services.email.contacts import ContactsService
from synapse.services.email.gmail import GmailService
from synapse.services.email.models import Contact, EmailMessage, EmailSummary
from synapse.services.email.protocols import ContactResolver, MailReader, MailSender
from synapse.services.email.smtp import SmtpConfig, SmtpService

__all__ = [
    "Contact",
    "ContactResolver",
    "ContactsService",
    "EmailMessage",
    "EmailSummary",
    "GmailService",
    "MailReader",
    "MailSender",
    "SmtpConfig",
    "SmtpService",
]
