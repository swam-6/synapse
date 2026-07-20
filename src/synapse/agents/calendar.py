"""The Calendar worker definition and its service wiring."""

from __future__ import annotations

from typing import Any

from synapse.agents.approval import ApprovalPolicy, apply_approvals
from synapse.agents.worker import WorkerSpec
from synapse.config.settings import AgentRole, Settings
from synapse.prompts.calendar import CALENDAR_AGENT_DESCRIPTION, CALENDAR_AGENT_PROMPT
from synapse.services.calendar.google_calendar import GoogleCalendarService
from synapse.services.calendar.protocols import CalendarGateway
from synapse.services.google.credentials import (
    ALL_GOOGLE_SCOPES,
    GoogleCredentialsProvider,
)
from synapse.tools.calendar import build_calendar_tools

CALENDAR_AGENT_NAME = "calendar_agent"


def build_calendar_gateway(settings: Settings) -> CalendarGateway:
    """Construct the Google Calendar service from configuration."""
    credentials = GoogleCredentialsProvider(
        token_path=settings.google_token_path,
        credentials_path=settings.google_credentials_path,
        scopes=ALL_GOOGLE_SCOPES,
    )
    return GoogleCalendarService(credentials, calendar_id=settings.calendar_id)


def build_calendar_worker_spec(
    settings: Settings, *, gateway: CalendarGateway | None = None
) -> WorkerSpec:
    """Return the Calendar worker spec, wiring the service and tools.

    Args:
        settings: Application settings (model + calendar id).
        gateway: Optional pre-built gateway used in tests; when ``None`` it is
            built from ``settings``.
    """
    resolved = gateway or build_calendar_gateway(settings)
    tools = apply_approvals(
        build_calendar_tools(
            resolved,
            default_max_results=settings.calendar_max_results,
            user_tz=settings.tzinfo(),
        ),
        [
            ApprovalPolicy("create_event", _summarize_create_event),
            ApprovalPolicy("delete_event", _summarize_delete_event),
        ],
        enabled=settings.require_approval_for_writes,
    )
    return WorkerSpec(
        name=CALENDAR_AGENT_NAME,
        description=CALENDAR_AGENT_DESCRIPTION,
        prompt=CALENDAR_AGENT_PROMPT,
        tools=tools,
        model_spec=settings.model_spec_for(AgentRole.CALENDAR),
    )


def _summarize_create_event(args: dict[str, Any]) -> str:
    return (
        f"Create a calendar event {args.get('summary')!r} from "
        f"{args.get('start')} to {args.get('end')}?"
    )


def _summarize_delete_event(args: dict[str, Any]) -> str:
    # Deletion is irreversible, so the confirmation names the exact event.
    return (
        f"Permanently DELETE the calendar event {args.get('summary')!r} "
        f"starting {args.get('start')}? This cannot be undone."
    )
