"""List Google calendars visible to the configured OAuth token.

Run after ``scripts.setup_google_oauth`` when you need the exact
``SYNAPSE_CALENDAR_ID`` value:

    python -m scripts.list_google_calendars
"""

from __future__ import annotations

import sys

from synapse.config.settings import get_settings
from synapse.services.google.credentials import (
    ALL_GOOGLE_SCOPES,
    GoogleCredentialsProvider,
)


async def _main() -> int:
    settings = get_settings()
    provider = GoogleCredentialsProvider(
        token_path=settings.google_token_path,
        credentials_path=settings.google_credentials_path,
        scopes=ALL_GOOGLE_SCOPES,
    )

    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("google-api-python-client is not installed; run `poetry install`.", file=sys.stderr)
        return 2

    creds = await provider.get_credentials()
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    response = service.calendarList().list().execute()
    calendars = response.get("items", [])
    if not calendars:
        print("No Google calendars are visible to this token.")
        return 0

    for calendar in calendars:
        summary = calendar.get("summary", "(no title)")
        calendar_id = calendar.get("id", "")
        primary = " primary" if calendar.get("primary") else ""
        selected = " selected" if calendar.get("selected") else ""
        print(f"{summary}{primary}{selected}\n  id: {calendar_id}")
    return 0


def main() -> int:
    import asyncio

    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
