"""Google OAuth credential loading and refresh.

Provides authorised :class:`google.oauth2.credentials.Credentials` for the Gmail
(read) and People APIs from a stored user token, refreshing it when expired. The
initial interactive OAuth consent that produces the token file is a one-time
setup step performed outside the running service; at runtime we only load and
refresh.

The ``google-auth`` imports are deferred to call time so this module — and the
whole services package — imports without the Google SDK installed, keeping unit
tests that use fakes dependency-free.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from synapse.errors import AuthenticationError
from synapse.observability.logging import get_logger

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

logger = get_logger(__name__)

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CONTACTS_READONLY_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"

# The union of every Google scope Synapse uses. The one-time OAuth consent that
# produces token.json must be granted this full set, since a single stored token
# is shared by the Gmail, People, and Calendar services.
ALL_GOOGLE_SCOPES = [
    GMAIL_READONLY_SCOPE,
    CONTACTS_READONLY_SCOPE,
    CALENDAR_SCOPE,
]


class GoogleCredentialsProvider:
    """Loads and refreshes a stored Google OAuth user token on demand."""

    def __init__(
        self,
        *,
        token_path: Path | None,
        credentials_path: Path | None,
        scopes: list[str],
    ) -> None:
        self._token_path = token_path
        self._credentials_path = credentials_path
        self._scopes = scopes
        self._cached: Credentials | None = None

    async def get_credentials(self) -> Credentials:
        """Return valid credentials, refreshing and re-persisting if needed.

        The blocking file and network work runs in a worker thread so the event
        loop is never stalled.

        Raises:
            AuthenticationError: if the token file is missing or cannot be
                loaded/refreshed.
        """
        if self._cached is not None and self._cached.valid:
            return self._cached
        self._cached = await asyncio.to_thread(self._load_or_refresh)
        return self._cached

    def _load_or_refresh(self) -> Credentials:
        """Synchronously load the token and refresh it if it has expired."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise AuthenticationError(
                "google-auth is not installed; run `poetry install`."
            ) from exc

        if self._token_path is None or not self._token_path.exists():
            raise AuthenticationError(
                "Google token file is not configured or does not exist. "
                "Complete the one-time OAuth setup to create it."
            )

        creds = Credentials.from_authorized_user_file(
            str(self._token_path), self._scopes
        )
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self._token_path.write_text(creds.to_json(), encoding="utf-8")
                logger.info("google_token_refreshed")
            else:
                raise AuthenticationError(
                    "Google credentials are invalid and cannot be refreshed; "
                    "re-run the OAuth setup."
                )
        return creds
