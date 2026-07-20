"""Google Calendar API v3 service.

Lists events, checks availability via a free/busy query, and creates events,
returning validated :class:`CalendarEvent` / :class:`BusyInterval` models. The
client is built lazily and cached; all blocking API work runs in a worker thread.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

from synapse.errors import ExternalServiceError
from synapse.observability.logging import get_logger
from synapse.services.calendar.models import BusyInterval, CalendarEvent
from synapse.services.google.credentials import GoogleCredentialsProvider
from synapse.utils.datetime import to_rfc3339

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource

logger = get_logger(__name__)


def _event_boundary(node: dict[str, Any]) -> str:
    """Extract an ISO boundary from a Calendar start/end node (datetime or date)."""
    return node.get("dateTime") or node.get("date") or ""


def _event_from_api(item: dict[str, Any]) -> CalendarEvent:
    """Map a Calendar API event resource to a :class:`CalendarEvent`."""
    return CalendarEvent(
        id=item.get("id", ""),
        summary=item.get("summary", "(no title)"),
        start=_event_boundary(item.get("start", {})),
        end=_event_boundary(item.get("end", {})),
        location=item.get("location"),
        html_link=item.get("htmlLink"),
    )


class GoogleCalendarService:
    """Reads and writes Google Calendar events (``CalendarGateway``)."""

    def __init__(self, credentials: GoogleCredentialsProvider, *, calendar_id: str) -> None:
        self._credentials = credentials
        self._calendar_id = calendar_id
        self._client: Resource | None = None

    async def _resource(self) -> Resource:
        if self._client is None:
            creds = await self._credentials.get_credentials()
            self._client = await asyncio.to_thread(self._build_client, creds)
        return self._client

    @staticmethod
    def _build_client(creds: Any) -> Resource:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ExternalServiceError(
                "google-api-python-client is not installed; run `poetry install`."
            ) from exc
        return build("calendar", "v3", credentials=creds, cache_discovery=False, static_discovery=True)

    async def list_events(
        self, *, time_min: datetime, time_max: datetime | None, max_results: int
    ) -> list[CalendarEvent]:
        """Return events between ``time_min`` and ``time_max`` (or upcoming)."""
        await self._resource()
        try:
            return await asyncio.to_thread(
                self._list_events_blocking, time_min, time_max, max_results
            )
        except ExternalServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise provider errors
            raise ExternalServiceError(f"Failed to list calendar events: {exc}") from exc

    def _list_events_blocking(
        self, time_min: datetime, time_max: datetime | None, max_results: int
    ) -> list[CalendarEvent]:
        client = self._client
        assert client is not None
        params: dict[str, Any] = {
            "calendarId": self._calendar_id,
            "timeMin": to_rfc3339(time_min),
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_max is not None:
            params["timeMax"] = to_rfc3339(time_max)
        response = client.events().list(**params).execute()
        return [_event_from_api(item) for item in response.get("items", [])]

    async def check_availability(
        self, *, time_min: datetime, time_max: datetime
    ) -> list[BusyInterval]:
        """Return busy intervals in the window (empty means fully free)."""
        await self._resource()
        try:
            return await asyncio.to_thread(self._check_availability_blocking, time_min, time_max)
        except ExternalServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise provider errors
            raise ExternalServiceError(f"Failed to check availability: {exc}") from exc

    def _check_availability_blocking(
        self, time_min: datetime, time_max: datetime
    ) -> list[BusyInterval]:
        client = self._client
        assert client is not None
        body = {
            "timeMin": to_rfc3339(time_min),
            "timeMax": to_rfc3339(time_max),
            "items": [{"id": self._calendar_id}],
        }
        response = client.freebusy().query(body=body).execute()
        calendars = response.get("calendars", {})
        busy = calendars.get(self._calendar_id, {}).get("busy", [])
        return [BusyInterval(start=slot["start"], end=slot["end"]) for slot in busy]

    async def create_event(
        self,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        location: str | None = None,
        description: str | None = None,
    ) -> CalendarEvent:
        """Create an event and return it as stored."""
        await self._resource()
        try:
            return await asyncio.to_thread(
                self._create_event_blocking, summary, start, end, location, description
            )
        except ExternalServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise provider errors
            raise ExternalServiceError(f"Failed to create calendar event: {exc}") from exc

    def _create_event_blocking(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        location: str | None,
        description: str | None,
    ) -> CalendarEvent:
        client = self._client
        assert client is not None
        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": to_rfc3339(start)},
            "end": {"dateTime": to_rfc3339(end)},
        }
        if location is not None:
            body["location"] = location
        if description is not None:
            body["description"] = description
        created = client.events().insert(calendarId=self._calendar_id, body=body).execute()
        logger.info("calendar_event_created", event_id=created.get("id"))
        return _event_from_api(created)

    async def delete_event(self, *, event_id: str) -> None:
        """Permanently delete the event with ``event_id``."""
        await self._resource()
        try:
            await asyncio.to_thread(self._delete_event_blocking, event_id)
        except ExternalServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise provider errors
            raise ExternalServiceError(
                f"Failed to delete calendar event {event_id!r}: {exc}"
            ) from exc

    def _delete_event_blocking(self, event_id: str) -> None:
        client = self._client
        assert client is not None
        client.events().delete(calendarId=self._calendar_id, eventId=event_id).execute()
        logger.info("calendar_event_deleted", event_id=event_id)
