"""Notion API service for the to-do database.

Reads, creates, and updates to-do tasks via Notion's native async client, using
the exact property names and status values defined in
:mod:`synapse.services.notion.models`.
Returns validated :class:`NotionTask` models. The client is built lazily and
cached; ``notion-client`` is imported lazily so the package stays importable
without the SDK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from synapse.errors import ExternalServiceError
from synapse.observability.logging import get_logger
from synapse.services.notion.models import (
    DATE_PROPERTY,
    STATUS_PROPERTY,
    TITLE_PROPERTY,
    NotionTask,
)

if TYPE_CHECKING:
    from notion_client import AsyncClient

logger = get_logger(__name__)


def _plain_title(prop: dict[str, Any]) -> str:
    """Concatenate the plain text of a Notion ``title`` property value."""
    return "".join(part.get("plain_text", "") for part in prop.get("title", []))


def _status_name(prop: dict[str, Any]) -> str | None:
    """Return the selected status name, or ``None`` if unset."""
    status = prop.get("status")
    return status.get("name") if status else None


def _date_start(prop: dict[str, Any]) -> str | None:
    """Return the ISO start of a Notion ``date`` property, or ``None``."""
    date = prop.get("date")
    return date.get("start") if date else None


def _task_from_page(page: dict[str, Any]) -> NotionTask:
    """Map a Notion page object to a :class:`NotionTask` using the exact schema."""
    props = page.get("properties", {})
    return NotionTask(
        id=page.get("id", ""),
        title=_plain_title(props.get(TITLE_PROPERTY, {})),
        status=_status_name(props.get(STATUS_PROPERTY, {})),
        due_date=_date_start(props.get(DATE_PROPERTY, {})),
        url=page.get("url"),
    )


class NotionService:
    """Reads, creates, and updates Notion to-do tasks (``NotionGateway``)."""

    def __init__(self, *, api_key: SecretStr, database_id: str, max_results: int = 25) -> None:
        self._api_key = api_key
        self._database_id = database_id
        self._max_results = max_results
        self._client: AsyncClient | None = None

    def _get_client(self) -> AsyncClient:
        if self._client is None:
            try:
                from notion_client import AsyncClient
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise ExternalServiceError(
                    "notion-client is not installed; run `poetry install`."
                ) from exc
            self._client = AsyncClient(auth=self._api_key.get_secret_value())
        return self._client

    async def list_tasks(
        self,
        *,
        status: str | None = None,
        due_before: str | None = None,
        due_after: str | None = None,
    ) -> list[NotionTask]:
        """Return tasks, optionally filtered by status and/or due-date bounds."""
        client = self._get_client()
        query: dict[str, Any] = {
            "database_id": self._database_id,
            "page_size": self._max_results,
        }
        composed = _build_filter(status, due_before, due_after)
        if composed is not None:
            query["filter"] = composed
        try:
            response = await client.databases.query(**query)
        except Exception as exc:  # noqa: BLE001 - normalise Notion SDK errors
            raise ExternalServiceError(f"Failed to query Notion tasks: {exc}") from exc
        return [_task_from_page(page) for page in response.get("results", [])]

    async def create_task(
        self, *, title: str, status: str, due_date: str | None = None
    ) -> NotionTask:
        """Create a task with the given title, status, and optional due date."""
        client = self._get_client()
        properties: dict[str, Any] = {
            TITLE_PROPERTY: {"title": [{"text": {"content": title}}]},
            STATUS_PROPERTY: {"status": {"name": status}},
        }
        if due_date is not None:
            properties[DATE_PROPERTY] = {"date": {"start": due_date}}
        try:
            page = await client.pages.create(
                parent={"database_id": self._database_id}, properties=properties
            )
        except Exception as exc:  # noqa: BLE001 - normalise Notion SDK errors
            raise ExternalServiceError(f"Failed to create Notion task: {exc}") from exc
        logger.info("notion_task_created", task_id=page.get("id"))
        return _task_from_page(page)

    async def update_task_status(self, *, title: str, status: str) -> NotionTask:
        """Update the status of exactly one task matched by title."""
        client = self._get_client()
        try:
            response = await client.databases.query(
                database_id=self._database_id,
                page_size=2,
                filter={"property": TITLE_PROPERTY, "title": {"equals": title}},
            )
        except Exception as exc:  # noqa: BLE001 - normalise Notion SDK errors
            raise ExternalServiceError(f"Failed to find Notion task: {exc}") from exc

        matches = response.get("results", [])
        if not matches:
            raise ExternalServiceError(f"No Notion task found with title {title!r}.")
        if len(matches) > 1:
            raise ExternalServiceError(
                f"Multiple Notion tasks found with title {title!r}; please rename one first."
            )

        page_id = matches[0].get("id", "")
        try:
            page = await client.pages.update(
                page_id=page_id,
                properties={STATUS_PROPERTY: {"status": {"name": status}}},
            )
        except Exception as exc:  # noqa: BLE001 - normalise Notion SDK errors
            raise ExternalServiceError(f"Failed to update Notion task: {exc}") from exc
        logger.info("notion_task_updated", task_id=page.get("id"))
        return _task_from_page(page)


def _build_filter(
    status: str | None, due_before: str | None, due_after: str | None
) -> dict[str, Any] | None:
    """Compose a Notion query filter from the optional criteria."""
    conditions: list[dict[str, Any]] = []
    if status is not None:
        conditions.append({"property": STATUS_PROPERTY, "status": {"equals": status}})
    if due_before is not None:
        conditions.append({"property": DATE_PROPERTY, "date": {"on_or_before": due_before}})
    if due_after is not None:
        conditions.append({"property": DATE_PROPERTY, "date": {"on_or_after": due_after}})
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"and": conditions}
