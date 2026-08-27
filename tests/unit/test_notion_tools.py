"""Unit tests for the Notion worker tools using a fake gateway."""

from __future__ import annotations

import pytest

from synapse.errors import ExternalServiceError
from synapse.services.notion.models import NotionTask
from synapse.tools.notion import build_notion_tools


class _FakeGateway:
    def __init__(self, *, tasks=None, created=None, updated=None, error=None):
        self._tasks = tasks or []
        self._created = created
        self._updated = updated
        self._error = error
        self.list_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []

    async def list_tasks(self, *, status=None, due_before=None, due_after=None):
        if self._error:
            raise self._error
        self.list_calls.append(
            {"status": status, "due_before": due_before, "due_after": due_after}
        )
        return self._tasks

    async def create_task(self, *, title, status, due_date=None):
        if self._error:
            raise self._error
        self.create_calls.append({"title": title, "status": status, "due_date": due_date})
        return self._created or NotionTask(
            id="n1", title=title, status=status, due_date=due_date
        )

    async def update_task_status(self, *, title, status):
        if self._error:
            raise self._error
        self.update_calls.append({"title": title, "status": status})
        return self._updated or NotionTask(id="n1", title=title, status=status)


def _tools(gateway) -> dict:
    return {t.name: t for t in build_notion_tools(gateway)}


@pytest.mark.asyncio
async def test_list_tasks_formats() -> None:
    gw = _FakeGateway(
        tasks=[NotionTask(id="n1", title="Write report", status="In progress", due_date="2026-07-20")]
    )
    result = await _tools(gw)["list_tasks"].ainvoke({})
    assert "Write report" in result and "[In progress]" in result and "due 2026-07-20" in result


@pytest.mark.asyncio
async def test_list_tasks_rejects_invalid_status() -> None:
    gw = _FakeGateway()
    result = await _tools(gw)["list_tasks"].ainvoke({"status": "Doing"})
    assert "not a valid status" in result
    assert gw.list_calls == []


@pytest.mark.asyncio
async def test_list_tasks_rejects_bad_date() -> None:
    gw = _FakeGateway()
    result = await _tools(gw)["list_tasks"].ainvoke({"due_before": "next week"})
    assert "not a valid ISO date" in result


@pytest.mark.asyncio
async def test_create_task_defaults_status_and_confirms() -> None:
    gw = _FakeGateway()
    result = await _tools(gw)["create_task"].ainvoke({"title": "Buy milk"})
    assert "Added task 'Buy milk'" in result and "Not started" in result
    assert gw.create_calls == [{"title": "Buy milk", "status": "Not started", "due_date": None}]


@pytest.mark.asyncio
async def test_create_task_with_due_date() -> None:
    gw = _FakeGateway()
    result = await _tools(gw)["create_task"].ainvoke(
        {"title": "Submit", "status": "In progress", "due_date": "2026-07-31"}
    )
    assert "due 2026-07-31" in result
    assert gw.create_calls[0]["status"] == "In progress"


@pytest.mark.asyncio
async def test_create_task_rejects_invalid_status() -> None:
    gw = _FakeGateway()
    result = await _tools(gw)["create_task"].ainvoke({"title": "X", "status": "Later"})
    assert "not a valid status" in result
    assert gw.create_calls == []


@pytest.mark.asyncio
async def test_create_task_reports_service_error() -> None:
    gw = _FakeGateway(error=ExternalServiceError("notion down"))
    result = await _tools(gw)["create_task"].ainvoke({"title": "X"})
    assert "Could not create the task" in result and "notion down" in result


@pytest.mark.asyncio
async def test_update_task_status_confirms() -> None:
    gw = _FakeGateway()
    result = await _tools(gw)["update_task_status"].ainvoke(
        {"title": "pay rent", "status": "Done"}
    )
    assert "Updated task 'pay rent' to status 'Done'" in result
    assert gw.update_calls == [{"title": "pay rent", "status": "Done"}]


@pytest.mark.asyncio
async def test_update_task_status_rejects_invalid_status() -> None:
    gw = _FakeGateway()
    result = await _tools(gw)["update_task_status"].ainvoke(
        {"title": "pay rent", "status": "Finished"}
    )
    assert "not a valid status" in result
    assert gw.update_calls == []


@pytest.mark.asyncio
async def test_update_task_status_reports_service_error() -> None:
    gw = _FakeGateway(error=ExternalServiceError("No Notion task found with title 'x'."))
    result = await _tools(gw)["update_task_status"].ainvoke(
        {"title": "x", "status": "Done"}
    )
    assert "Could not update the task" in result
    assert "No Notion task found" in result
