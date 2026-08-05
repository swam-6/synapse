"""LangChain tools for the Notion worker.

Thin, validated wrappers over the :class:`NotionGateway`. Status values are
checked against the exact allowed set and due dates against ISO 8601 before any
call; on invalid input or a service failure the tool returns an agent-readable
message rather than raising.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from synapse.errors import ExternalServiceError
from synapse.observability.logging import get_logger
from synapse.services.notion.models import (
    ALLOWED_STATUSES,
    DEFAULT_STATUS,
    NotionTask,
)
from synapse.services.notion.protocols import NotionGateway
from synapse.utils.datetime import is_iso_datelike

logger = get_logger(__name__)

_ALLOWED = ", ".join(f'"{s}"' for s in ALLOWED_STATUSES)


class CreateTaskInput(BaseModel):
    """Validated arguments for creating a Notion task."""

    title: str = Field(min_length=1, description="The task text.")
    status: str = Field(
        default=DEFAULT_STATUS.value,
        description=f'Task status; one of {_ALLOWED}. Defaults to "{DEFAULT_STATUS.value}".',
    )
    due_date: str | None = Field(
        default=None, description="Optional due date as an ISO 8601 date (YYYY-MM-DD)."
    )


class UpdateTaskStatusInput(BaseModel):
    """Validated arguments for updating a Notion task's status."""

    title: str = Field(min_length=1, description="The exact task title to update.")
    status: str = Field(description=f"New task status; one of {_ALLOWED}.")


def _format_tasks(tasks: list[NotionTask]) -> str:
    if not tasks:
        return "No matching to-do tasks were found."
    lines = []
    for index, task in enumerate(tasks, start=1):
        due = f" | due {task.due_date}" if task.due_date else ""
        status = f" [{task.status}]" if task.status else ""
        lines.append(f"{index}. {task.title}{status}{due}")
    return "\n".join(lines)


def build_notion_tools(gateway: NotionGateway) -> list[BaseTool]:
    """Build the Notion worker's tools bound to ``gateway``."""

    @tool
    async def list_tasks(
        status: str | None = None,
        due_before: str | None = None,
        due_after: str | None = None,
    ) -> str:
        """List to-do tasks, optionally filtered by status and/or due-date bounds.

        ``status`` must be one of the allowed values; ``due_before``/``due_after``
        are ISO 8601 dates (YYYY-MM-DD).
        """
        if status is not None and status not in ALLOWED_STATUSES:
            return f"{status!r} is not a valid status. Allowed values: {_ALLOWED}."
        for label, value in (("due_before", due_before), ("due_after", due_after)):
            if value is not None and not is_iso_datelike(value):
                return f"{label} {value!r} is not a valid ISO date (use YYYY-MM-DD)."
        try:
            tasks = await gateway.list_tasks(
                status=status, due_before=due_before, due_after=due_after
            )
        except ExternalServiceError as exc:
            logger.warning("tool_list_tasks_failed", error=str(exc))
            return f"Could not read the to-do list: {exc}"
        return _format_tasks(tasks)

    @tool(args_schema=CreateTaskInput)
    async def create_task(
        title: str, status: str = DEFAULT_STATUS.value, due_date: str | None = None
    ) -> str:
        """Create a to-do task with a title, status, and optional due date."""
        if status not in ALLOWED_STATUSES:
            return f"{status!r} is not a valid status. Allowed values: {_ALLOWED}."
        if due_date is not None and not is_iso_datelike(due_date):
            return f"due_date {due_date!r} is not a valid ISO date (use YYYY-MM-DD)."
        try:
            task = await gateway.create_task(title=title, status=status, due_date=due_date)
        except ExternalServiceError as exc:
            logger.warning("tool_create_task_failed", error=str(exc))
            return f"Could not create the task: {exc}"
        due = f" (due {task.due_date})" if task.due_date else ""
        return f"Added task '{task.title}' with status '{task.status}'{due}."

    @tool(args_schema=UpdateTaskStatusInput)
    async def update_task_status(title: str, status: str) -> str:
        """Update the status of an existing task matched by exact title."""
        if status not in ALLOWED_STATUSES:
            return f"{status!r} is not a valid status. Allowed values: {_ALLOWED}."
        try:
            task = await gateway.update_task_status(title=title, status=status)
        except ExternalServiceError as exc:
            logger.warning("tool_update_task_status_failed", error=str(exc))
            return f"Could not update the task: {exc}"
        return f"Updated task '{task.title}' to status '{task.status}'."

    return [list_tasks, create_task, update_task_status]
