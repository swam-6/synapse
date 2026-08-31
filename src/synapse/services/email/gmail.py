"""Gmail read service.

Lists recent inbox messages and fetches full messages via the Gmail REST API,
returning validated :class:`EmailSummary` / :class:`EmailMessage` models. The
Gmail client is built lazily and cached; all blocking API work runs in a worker
thread. Summarisation itself is the LLM's job — this service only fetches and
shapes data.
"""

from __future__ import annotations

import asyncio
import base64
import re
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup

from synapse.errors import ExternalServiceError
from synapse.observability.logging import get_logger
from synapse.services.email.models import EmailMessage, EmailSummary
from synapse.services.google.credentials import GoogleCredentialsProvider

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource

logger = get_logger(__name__)

_METADATA_HEADERS = ("From", "Subject", "Date")
_MAX_BODY_LENGTH = 4000


def _header(headers: list[dict[str, str]], name: str) -> str:
    """Return the value of the named header (case-insensitive), or empty string."""
    lowered = name.lower()
    for header in headers:
        if header.get("name", "").lower() == lowered:
            return header.get("value", "")
    return ""


def _clean_text(text: str) -> str:
    """Collapse excessive whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def _decode_part(data: str) -> str:
    """Decode a Gmail base64url-encoded body."""
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def _extract_text(payload: dict[str, Any]) -> str:
    """Extract readable text from a Gmail payload.

    Preference order:
        1. text/plain
        2. text/html (converted to plain text)
        3. top-level body
    """
    html_fallback: str | None = None

    stack: list[dict[str, Any]] = [payload]

    while stack:
        part = stack.pop()

        mime = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")

        if mime == "text/plain" and data:
            return _clean_text(_decode_part(data))

        if mime == "text/html" and data and html_fallback is None:
            html = _decode_part(data)
            html_fallback = BeautifulSoup(html, "html.parser").get_text(
                separator=" ",
                strip=True,
            )

        stack.extend(part.get("parts", []))

    if html_fallback:
        return _clean_text(html_fallback)

    data = payload.get("body", {}).get("data")
    if data:
        text = _decode_part(data)
        if "<html" in text.lower():
            text = BeautifulSoup(text, "html.parser").get_text(
                separator=" ",
                strip=True,
            )
        return _clean_text(text)

    return ""


class GmailService:
    """Reads Gmail inbox messages for the authenticated user (``MailReader``)."""

    def __init__(self, credentials: GoogleCredentialsProvider) -> None:
        self._credentials = credentials
        self._client: Resource | None = None

    async def _resource(self) -> Resource:
        """Return the cached Gmail API client, building it on first use."""
        if self._client is None:
            creds = await self._credentials.get_credentials()
            self._client = await asyncio.to_thread(self._build_client, creds)
        return self._client

    @staticmethod
    def _build_client(creds: Any) -> Resource:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise ExternalServiceError(
                "google-api-python-client is not installed; run `poetry install`."
            ) from exc

        return build(
            "gmail",
            "v1",
            credentials=creds,
            cache_discovery=False,
            static_discovery=True,
        )

    async def list_recent(self, max_results: int) -> list[EmailSummary]:
        """Return up to ``max_results`` most recent inbox messages as summaries."""
        await self._resource()
        try:
            return await asyncio.to_thread(self._list_recent_blocking, max_results)
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise ExternalServiceError(
                f"Failed to list Gmail messages: {exc}"
            ) from exc

    def _list_recent_blocking(self, max_results: int) -> list[EmailSummary]:
        client = self._client
        assert client is not None

        listing = (
            client.users()
            .messages()
            .list(
                userId="me",
                maxResults=max_results,
                labelIds=["INBOX"],
            )
            .execute()
        )

        summaries: list[EmailSummary] = []

        for ref in listing.get("messages", []):
            msg = (
                client.users()
                .messages()
                .get(
                    userId="me",
                    id=ref["id"],
                    format="metadata",
                    metadataHeaders=list(_METADATA_HEADERS),
                )
                .execute()
            )

            headers = msg.get("payload", {}).get("headers", [])

            summaries.append(
                EmailSummary(
                    id=msg["id"],
                    sender=_header(headers, "From"),
                    subject=_header(headers, "Subject"),
                    date=_header(headers, "Date"),
                    snippet=msg.get("snippet", ""),
                )
            )

        return summaries

    async def get_message(self, message_id: str) -> EmailMessage:
        """Return the full message (with body) for ``message_id``."""
        await self._resource()

        try:
            return await asyncio.to_thread(
                self._get_message_blocking,
                message_id,
            )
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise ExternalServiceError(
                f"Failed to fetch Gmail message {message_id!r}: {exc}"
            ) from exc

    def _get_message_blocking(self, message_id: str) -> EmailMessage:
        client = self._client
        assert client is not None

        msg = (
            client.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="full",
            )
            .execute()
        )

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])

        body = _extract_text(payload)

        if len(body) > _MAX_BODY_LENGTH:
            body = body[:_MAX_BODY_LENGTH] + "\n\n...[message truncated]"

        return EmailMessage(
            id=msg["id"],
            sender=_header(headers, "From"),
            subject=_header(headers, "Subject"),
            date=_header(headers, "Date"),
            snippet=msg.get("snippet", ""),
            body=body,
        )