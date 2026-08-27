"""Blank environment variables must read as "not configured", not empty values.

A ``.env`` copied from ``.env.example`` contains placeholder lines such as
``SYNAPSE_TELEGRAM_WEBHOOK_SECRET=``. Regression guard: those must resolve to
``None`` so secret verification stays off and providers report a clear
"not configured" error rather than failing later with an empty credential.
"""

from __future__ import annotations

import pytest

from synapse.api.security import verify_secret_token
from synapse.config.settings import LLMProvider, Settings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_secret_is_unset(blank: str) -> None:
    settings = _settings(telegram_webhook_secret=blank)  # type: ignore[arg-type]
    assert settings.telegram_webhook_secret is None


def test_blank_webhook_secret_does_not_enable_verification() -> None:
    # The exact bug: a blank secret must not reject every inbound request.
    settings = _settings(telegram_webhook_secret="")  # type: ignore[arg-type]
    assert verify_secret_token(None, settings.telegram_webhook_secret) is True


def test_blank_api_key_reads_as_not_configured() -> None:
    settings = _settings(groq_api_key="")  # type: ignore[arg-type]
    assert settings.api_key_for(LLMProvider.GROQ) is None


def test_blank_optional_paths_and_models_are_unset() -> None:
    settings = _settings(google_token_path="", manager_llm_model="", notion_database_id="")  # type: ignore[arg-type]
    assert settings.google_token_path is None
    assert settings.manager_llm_model is None
    assert settings.notion_database_id is None


def test_real_values_still_pass_through() -> None:
    settings = _settings(telegram_webhook_secret="s3cret", groq_api_key="gsk_x")  # type: ignore[arg-type]
    assert settings.telegram_webhook_secret.get_secret_value() == "s3cret"  # type: ignore[union-attr]
    assert verify_secret_token("s3cret", settings.telegram_webhook_secret) is True
