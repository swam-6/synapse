"""Unit tests for typed configuration and per-role model resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from synapse.config.settings import AgentRole, LLMProvider, Settings


def _settings(**overrides: str) -> Settings:
    """Build Settings from an explicit dict, ignoring any on-disk .env."""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_defaults_match_specification() -> None:
    settings = _settings()
    assert settings.environment == "development"
    assert settings.default_llm_provider is LLMProvider.OPENAI
    assert settings.default_llm_model == "gpt-4o"
    assert settings.sqlite_path == Path("db/checkpoints.sqlite")


def test_secrets_are_not_exposed_in_repr() -> None:
    settings = _settings(openai_api_key="sk-super-secret")  # type: ignore[arg-type]
    assert "sk-super-secret" not in repr(settings)
    assert isinstance(settings.openai_api_key, SecretStr)
    assert settings.openai_api_key.get_secret_value() == "sk-super-secret"


def test_api_key_for_maps_provider_to_credential() -> None:
    settings = _settings(
        openai_api_key="k-openai",  # type: ignore[arg-type]
        groq_api_key="k-groq",  # type: ignore[arg-type]
    )
    assert settings.api_key_for(LLMProvider.OPENAI).get_secret_value() == "k-openai"  # type: ignore[union-attr]
    assert settings.api_key_for(LLMProvider.GROQ).get_secret_value() == "k-groq"  # type: ignore[union-attr]
    assert settings.api_key_for(LLMProvider.GEMINI) is None


def test_model_spec_falls_back_to_defaults() -> None:
    settings = _settings()
    spec = settings.model_spec_for(AgentRole.EMAIL)
    assert spec.provider is LLMProvider.OPENAI
    assert spec.model == "gpt-4o"
    assert spec.temperature == 0.0


def test_per_role_override_replaces_only_model_name() -> None:
    settings = _settings(email_llm_model="gpt-4o-mini")
    manager_spec = settings.model_spec_for(AgentRole.MANAGER)
    email_spec = settings.model_spec_for(AgentRole.EMAIL)
    assert manager_spec.model == "gpt-4o"
    assert email_spec.model == "gpt-4o-mini"
    # Provider and resilience params stay shared.
    assert email_spec.provider is manager_spec.provider


def test_model_spec_is_frozen_and_hashable() -> None:
    spec = _settings().model_spec_for(AgentRole.MANAGER)
    assert hash(spec) == hash(_settings().model_spec_for(AgentRole.MANAGER))
    with pytest.raises(Exception):  # noqa: B017 - pydantic raises ValidationError
        spec.model = "other"  # type: ignore[misc]
