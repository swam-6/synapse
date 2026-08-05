"""The Notion worker definition and its service wiring."""

from __future__ import annotations

from typing import Any

from synapse.agents.approval import ApprovalPolicy, apply_approvals
from synapse.agents.worker import WorkerSpec
from synapse.config.settings import AgentRole, Settings
from synapse.errors import ConfigurationError
from synapse.prompts.notion import NOTION_AGENT_DESCRIPTION, NOTION_AGENT_PROMPT
from synapse.services.notion.notion import NotionService
from synapse.services.notion.protocols import NotionGateway
from synapse.tools.notion import build_notion_tools

NOTION_AGENT_NAME = "notion_agent"


def build_notion_gateway(settings: Settings) -> NotionGateway:
    """Construct the Notion service from configuration.

    Raises:
        ConfigurationError: if the Notion API key or database id is not set.
    """
    if settings.notion_api_key is None or settings.notion_database_id is None:
        raise ConfigurationError(
            "SYNAPSE_NOTION_API_KEY and SYNAPSE_NOTION_DATABASE_ID are required "
            "for the Notion agent."
        )
    return NotionService(
        api_key=settings.notion_api_key,
        database_id=settings.notion_database_id,
        max_results=settings.notion_max_results,
    )


def build_notion_worker_spec(
    settings: Settings, *, gateway: NotionGateway | None = None
) -> WorkerSpec:
    """Return the Notion worker spec, wiring the service and tools."""
    resolved = gateway or build_notion_gateway(settings)
    tools = apply_approvals(
        build_notion_tools(resolved),
        [
            ApprovalPolicy("create_task", _summarize_create_task),
            ApprovalPolicy("update_task_status", _summarize_update_task_status),
        ],
        enabled=settings.require_approval_for_writes,
    )
    return WorkerSpec(
        name=NOTION_AGENT_NAME,
        description=NOTION_AGENT_DESCRIPTION,
        prompt=NOTION_AGENT_PROMPT,
        tools=tools,
        model_spec=settings.model_spec_for(AgentRole.NOTION),
    )


def _summarize_create_task(args: dict[str, Any]) -> str:
    due = f" due {args['due_date']}" if args.get("due_date") else ""
    return f"Add a to-do task {args.get('title')!r}{due}?"


def _summarize_update_task_status(args: dict[str, Any]) -> str:
    return f"Update to-do task {args.get('title')!r} to status {args.get('status')!r}?"
