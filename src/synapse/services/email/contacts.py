"""Contact resolution via the Google People API.

Resolves a person's display name to candidate email addresses so the Manager can
address mail by name. The People client is built lazily and cached; blocking API
work runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from synapse.errors import ExternalServiceError
from synapse.observability.logging import get_logger
from synapse.services.email.models import Contact
from synapse.services.google.credentials import GoogleCredentialsProvider

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource

logger = get_logger(__name__)

_READ_MASK = "names,emailAddresses"

# Google's People API search index is a lazy, server-side cache. A cold search
# reliably returns zero results even for contacts that exist -- the docs
# require a warmup request with an empty query, followed by a short wait,
# before the first real search. See:
# https://developers.google.com/people/v1/contacts#search_the_users_contacts
_WARMUP_WAIT_SECONDS = 2.0


class ContactsService:
    """Resolves names to contacts via Google People (``ContactResolver``)."""

    def __init__(self, credentials: GoogleCredentialsProvider) -> None:
        self._credentials = credentials
        self._client: Resource | None = None
        self._warmed_up = False

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
        return build("people", "v1", credentials=creds, cache_discovery=False, static_discovery=True)

    async def resolve(self, name: str) -> list[Contact]:
        """Return contacts whose name matches ``name`` (may be empty)."""
        await self._resource()
        try:
            return await asyncio.to_thread(self._resolve_blocking, name)
        except ExternalServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise provider errors
            raise ExternalServiceError(f"Failed to resolve contact {name!r}: {exc}") from exc

    def _resolve_blocking(self, name: str) -> list[Contact]:
        client = self._client
        assert client is not None
        self._warmup_cache_if_needed(client)
        
        # 1. Try searchContacts (fast, uses lazy index)
        response = (
            client.people()
            .searchContacts(query=name, readMask=_READ_MASK)
            .execute()
        )
        contacts = self._parse_contacts(response.get("results", []), name)
        if contacts:
            return contacts
            
        # 2. Fallback to connections.list (slower, but guaranteed up-to-date)
        logger.info("contact_search_empty_falling_back_to_connections", query=name)
        response = (
            client.people().connections()
            .list(resourceName="people/me", personFields=_READ_MASK, pageSize=1000)
            .execute()
        )
        all_connections = response.get("connections", [])
        
        query_lower = name.lower()
        matched = []
        for person in all_connections:
            display = _first_value(person.get("names", []), "displayName") or ""
            if query_lower in display.lower():
                matched.append({"person": person})
                
        return self._parse_contacts(matched, name)

    def _parse_contacts(self, results: list[dict[str, Any]], query: str) -> list[Contact]:
        contacts: list[Contact] = []
        for result in results:
            person = result.get("person", {})
            display = _first_value(person.get("names", []), "displayName") or query
            for email in person.get("emailAddresses", []):
                value = email.get("value")
                if value:
                    contacts.append(Contact(name=display, email=value))
        return contacts

    def _warmup_cache_if_needed(self, client: Resource) -> None:
        """Send the empty-query warmup search Google's docs require.

        Runs once per service lifetime (the search cache stays warm across
        subsequent calls). Blocking -- must be called from the worker thread.
        """
        if self._warmed_up:
            return
        client.people().searchContacts(query="", readMask=_READ_MASK).execute()
        time.sleep(_WARMUP_WAIT_SECONDS)
        self._warmed_up = True


def _first_value(items: list[dict[str, Any]], key: str) -> str | None:
    """Return the first non-empty ``key`` value from a People sub-record list."""
    for item in items:
        value = item.get(key)
        if value:
            return str(value)
    return None