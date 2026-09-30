"""The Email worker definition and its service wiring.

``build_email_worker_spec`` assembles the Email worker: it constructs the Gmail,
SMTP, and People services from settings (or accepts pre-built services for
testing), wraps them in tools, and returns the :class:`WorkerSpec` the Manager
registers. Services are constructed here but perform no I/O until first used, so
building the worker at startup needs no live credentials.
"""

from __future__ import annotations

from typing import Any

from synapse.agents.approval import ApprovalPolicy, apply_approvals
from synapse.agents.worker import WorkerSpec
from synapse.config.settings import AgentRole, Settings
from synapse.errors import ConfigurationError
from synapse.prompts.email import EMAIL_AGENT_DESCRIPTION, EMAIL_AGENT_PROMPT
from synapse.services.email.contacts import ContactsService
from synapse.services.email.gmail import GmailService
from synapse.services.email.protocols import ContactResolver, MailReader, MailSender
from synapse.services.email.smtp import SmtpConfig, SmtpService
from synapse.services.google.credentials import (
    CONTACTS_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GoogleCredentialsProvider,
)
from synapse.tools.email import build_email_tools

EMAIL_AGENT_NAME = "email_agent"


def build_email_services(
    settings: Settings,
) -> tuple[MailReader, MailSender, ContactResolver]:
    """Construct the Gmail, SMTP, and People services from configuration.

    Raises:
        ConfigurationError: if the SMTP send credentials are not configured.
    """
    credentials = GoogleCredentialsProvider(
        token_path=settings.google_token_path,
        credentials_path=settings.google_credentials_path,
        scopes=[GMAIL_READONLY_SCOPE, CONTACTS_READONLY_SCOPE],
    )
    if settings.smtp_username is None or settings.smtp_app_password is None:
        raise ConfigurationError(
            "SYNAPSE_SMTP_USERNAME and SYNAPSE_SMTP_APP_PASSWORD are required for "
            "the Email agent to send mail."
        )
    smtp = SmtpService(
        SmtpConfig(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            app_password=settings.smtp_app_password,
        )
    )
    return GmailService(credentials), smtp, ContactsService(credentials)


def build_email_worker_spec(
    settings: Settings,
    *,
    services: tuple[MailReader, MailSender, ContactResolver] | None = None,
) -> WorkerSpec:
    """Return the Email worker spec, wiring services and tools.

    Args:
        settings: Application settings (model + credentials).
        services: Optional pre-built ``(reader, sender, resolver)`` triple used
            in tests; when ``None`` they are built from ``settings``.
    """
    reader, sender, resolver = services or build_email_services(settings)
    tools = apply_approvals(
        build_email_tools(reader, sender, resolver),
        [ApprovalPolicy("send_email", _summarize_send_email)],
        enabled=settings.require_approval_for_writes,
    )
    return WorkerSpec(
        name=EMAIL_AGENT_NAME,
        description=EMAIL_AGENT_DESCRIPTION,
        prompt=EMAIL_AGENT_PROMPT,
        tools=tools,
        model_spec=settings.model_spec_for(AgentRole.EMAIL),
    )


def _summarize_send_email(args: dict[str, Any]) -> str:
    return (
        f"Send an email to {args.get('to')} with subject "
        f"{args.get('subject')!r}?"
    )
