"""One-time Google OAuth setup: produce the shared ``token.json``.

Runs the installed-app OAuth consent flow for the union of Google scopes Synapse
uses (Gmail read, People, Calendar) and writes the authorised user token to the
configured token path. Run once per deployment (and again if scopes change):

    poetry run python -m scripts.setup_google_oauth

Requires ``SYNAPSE_GOOGLE_CREDENTIALS_PATH`` (the OAuth client secret file) and
``SYNAPSE_GOOGLE_TOKEN_PATH`` (where to write the token) to be configured.
"""

from __future__ import annotations

import sys

from synapse.config.settings import get_settings
from synapse.services.google.credentials import ALL_GOOGLE_SCOPES


def main() -> int:
    """Run the OAuth consent flow and persist the token. Returns an exit code."""
    settings = get_settings()
    if settings.google_credentials_path is None or settings.google_token_path is None:
        print(
            "Set SYNAPSE_GOOGLE_CREDENTIALS_PATH and SYNAPSE_GOOGLE_TOKEN_PATH first.",
            file=sys.stderr,
        )
        return 2
    if not settings.google_credentials_path.exists():
        print(
            f"OAuth client secret not found at {settings.google_credentials_path}.",
            file=sys.stderr,
        )
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("google-auth-oauthlib is not installed; run `poetry install`.", file=sys.stderr)
        return 2

    flow = InstalledAppFlow.from_client_secrets_file(
        str(settings.google_credentials_path), ALL_GOOGLE_SCOPES
    )
    # Opens a browser for consent and captures the redirect on a local port.
    credentials = flow.run_local_server(port=0)
    settings.google_token_path.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Wrote Google token to {settings.google_token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
