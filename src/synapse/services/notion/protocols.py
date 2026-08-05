"""Capability interface for the Notion integration (Dependency Inversion)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from synapse.services.notion.models import NotionTask


@runtime_checkable
class NotionGateway(Protocol):
    """Reads and creates to-do tasks in the Notion database."""

    async def list_tasks(
        self,
        *,
        status: str | None = None,
        due_before: str | None = None,
        due_after: str | None = None,
    ) -> list[NotionTask]:
        """Return tasks, optionally filtered by status and/or due-date bounds."""
        ...

    async def create_task(
        self, *, title: str, status: str, due_date: str | None = None
    ) -> NotionTask:
        """Create a task and return it as stored."""
        ...

    async def update_task_status(self, *, title: str, status: str) -> NotionTask:
        """Update one task's status by exact title and return it as stored."""
        ...
