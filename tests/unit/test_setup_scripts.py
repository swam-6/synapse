"""Unit tests for the pure parts of the setup scripts."""

from __future__ import annotations

import pytest

from scripts.register_telegram_webhook import build_set_webhook_request
from synapse.config.settings import Settings


def test_build_set_webhook_request_includes_url_and_secret() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        telegram_bot_token="123:ABC",  # type: ignore[arg-type]
        telegram_webhook_secret="s3cret",  # type: ignore[arg-type]
    )
    url, payload = build_set_webhook_request("https://example.ngrok.app/", settings)

    assert url == "https://api.telegram.org/bot123:ABC/setWebhook"
    assert payload["url"] == "https://example.ngrok.app/telegram/webhook"
    assert payload["secret_token"] == "s3cret"
    assert payload["allowed_updates"] == ["message"]


def test_build_set_webhook_request_without_secret_omits_it() -> None:
    settings = Settings(_env_file=None, telegram_bot_token="123:ABC")  # type: ignore[call-arg,arg-type]
    _, payload = build_set_webhook_request("https://x.app", settings)
    assert "secret_token" not in payload


def test_build_set_webhook_request_requires_token() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        build_set_webhook_request("https://x.app", settings)
