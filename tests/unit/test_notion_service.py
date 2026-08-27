"""Unit tests for Notion page parsing and filter composition (no SDK/network)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from synapse.errors import ExternalServiceError
from synapse.services.notion.notion import (
    NotionService,
    _build_filter,
    _task_from_page,
)


def _page(title: str, status: str | None, date: str | None) -> dict:
    props: dict = {
        "Title": {"title": [{"plain_text": title}]},
        "Status": {"status": {"name": status} if status else None},
        "Date": {"date": {"start": date} if date else None},
    }
    return {"id": "abc123", "url": "http://notion/abc123", "properties": props}


def test_task_from_page_extracts_exact_schema() -> None:
    task = _task_from_page(_page("Write report", "In progress", "2026-07-20"))
    assert task.id == "abc123"
    assert task.title == "Write report"
    assert task.status == "In progress"
    assert task.due_date == "2026-07-20"
    assert task.url == "http://notion/abc123"


def test_task_from_page_handles_unset_status_and_date() -> None:
    task = _task_from_page(_page("Loose task", None, None))
    assert task.status is None
    assert task.due_date is None


def test_build_filter_none_when_no_criteria() -> None:
    assert _build_filter(None, None, None) is None


def test_build_filter_single_condition_unwrapped() -> None:
    f = _build_filter("Done", None, None)
    assert f == {"property": "Status", "status": {"equals": "Done"}}


def test_build_filter_combines_with_and() -> None:
    f = _build_filter("Not started", "2026-07-31", "2026-07-01")
    assert "and" in f
    assert len(f["and"]) == 3
    assert {"property": "Date", "date": {"on_or_before": "2026-07-31"}} in f["and"]
    assert {"property": "Date", "date": {"on_or_after": "2026-07-01"}} in f["and"]


class _FakeDatabases:
    def __init__(self, results: list[dict]) -> None:
        self.results = results
        self.query_calls: list[dict] = []

    async def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return {"results": self.results}


class _FakePages:
    def __init__(self, page: dict) -> None:
        self.page = page
        self.update_calls: list[dict] = []

    async def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return self.page


class _FakeClient:
    def __init__(self, *, query_results: list[dict], updated_page: dict) -> None:
        self.databases = _FakeDatabases(query_results)
        self.pages = _FakePages(updated_page)


@pytest.mark.asyncio
async def test_update_task_status_queries_exact_title_and_updates_status() -> None:
    original = _page("pay rent", "Not started", None)
    updated = _page("pay rent", "Done", None)
    client = _FakeClient(query_results=[original], updated_page=updated)
    service = NotionService(
        api_key=SecretStr("secret_test"), database_id="db123", max_results=25
    )
    service._client = client

    task = await service.update_task_status(title="pay rent", status="Done")

    assert task.title == "pay rent"
    assert task.status == "Done"
    assert client.databases.query_calls == [
        {
            "database_id": "db123",
            "page_size": 2,
            "filter": {"property": "Title", "title": {"equals": "pay rent"}},
        }
    ]
    assert client.pages.update_calls == [
        {
            "page_id": "abc123",
            "properties": {"Status": {"status": {"name": "Done"}}},
        }
    ]


@pytest.mark.asyncio
async def test_update_task_status_errors_when_title_not_found() -> None:
    client = _FakeClient(query_results=[], updated_page={})
    service = NotionService(
        api_key=SecretStr("secret_test"), database_id="db123", max_results=25
    )
    service._client = client

    with pytest.raises(ExternalServiceError, match="No Notion task found"):
        await service.update_task_status(title="pay rent", status="Done")


@pytest.mark.asyncio
async def test_update_task_status_errors_when_title_is_ambiguous() -> None:
    page = _page("pay rent", "Not started", None)
    client = _FakeClient(query_results=[page, page], updated_page={})
    service = NotionService(
        api_key=SecretStr("secret_test"), database_id="db123", max_results=25
    )
    service._client = client

    with pytest.raises(ExternalServiceError, match="Multiple Notion tasks"):
        await service.update_task_status(title="pay rent", status="Done")
