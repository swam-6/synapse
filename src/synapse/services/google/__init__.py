"""Shared Google authentication used by the Gmail and People integrations."""

from synapse.services.google.credentials import (
    ALL_GOOGLE_SCOPES,
    CALENDAR_SCOPE,
    CONTACTS_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GoogleCredentialsProvider,
)

__all__ = [
    "ALL_GOOGLE_SCOPES",
    "CALENDAR_SCOPE",
    "CONTACTS_READONLY_SCOPE",
    "GMAIL_READONLY_SCOPE",
    "GoogleCredentialsProvider",
]
