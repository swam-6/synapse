"""Register (or delete) the Telegram webhook for Synapse.

Points Telegram at the public URL of the FastAPI webhook and installs the secret
token so inbound calls can be authenticated. Run whenever the public URL changes
(e.g. a new ngrok tunnel):

    poetry run python -m scripts.register_telegram_webhook https://<public-host>
    poetry run python -m scripts.register_telegram_webhook --delete

Requires ``SYNAPSE_TELEGRAM_BOT_TOKEN`` (and ``SYNAPSE_TELEGRAM_WEBHOOK_SECRET``
to install the secret token).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import httpx

from synapse.config.settings import Settings, get_settings

WEBHOOK_PATH = "/telegram/webhook"


def build_set_webhook_request(
    base_url: str, settings: Settings
) -> tuple[str, dict[str, Any]]:
    """Build the (api_url, payload) for a setWebhook call. Pure and testable."""
    token = settings.telegram_bot_token
    if token is None:
        raise ValueError("SYNAPSE_TELEGRAM_BOT_TOKEN is not configured.")
    api_url = f"https://api.telegram.org/bot{token.get_secret_value()}/setWebhook"
    payload: dict[str, Any] = {
        "url": f"{base_url.rstrip('/')}{WEBHOOK_PATH}",
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
    }
    if settings.telegram_webhook_secret is not None:
        payload["secret_token"] = settings.telegram_webhook_secret.get_secret_value()
    return api_url, payload


def _delete_url(settings: Settings) -> str:
    token = settings.telegram_bot_token
    if token is None:
        raise ValueError("SYNAPSE_TELEGRAM_BOT_TOKEN is not configured.")
    return f"https://api.telegram.org/bot{token.get_secret_value()}/deleteWebhook"


def main(argv: list[str] | None = None) -> int:
    """Register or delete the webhook. Returns an exit code."""
    parser = argparse.ArgumentParser(description="Register the Telegram webhook.")
    parser.add_argument("base_url", nargs="?", help="Public base URL (https://...).")
    parser.add_argument("--delete", action="store_true", help="Delete the webhook instead.")
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        if args.delete:
            response = httpx.post(_delete_url(settings), timeout=15.0)
        else:
            if not args.base_url:
                parser.error("base_url is required unless --delete is given")
            url, payload = build_set_webhook_request(args.base_url, settings)
            response = httpx.post(url, json=payload, timeout=15.0)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    data = response.json()
    if not data.get("ok"):
        print(f"Telegram error: {data}", file=sys.stderr)
        return 1
    print("Webhook deleted." if args.delete else "Webhook registered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
