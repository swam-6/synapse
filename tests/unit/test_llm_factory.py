"""Unit tests for the provider-agnostic LLM factory.

These tests exercise the factory's contract — key enforcement, dispatch, and
caching — without constructing real vendor clients. A stub builder is injected in
place of the provider builders so no network or SDK is required.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from synapse.config.settings import LLMProvider, ModelSpec
from synapse.errors import LLMProviderError
from synapse.infrastructure.llm_factory import LLMFactory


class _StubChatModel:
    """Minimal stand-in for a BaseChatModel; identity is enough for caching tests."""

    def __init__(self, spec: ModelSpec) -> None:
        self.spec = spec


def _spec(provider: LLMProvider = LLMProvider.OPENAI) -> ModelSpec:
    return ModelSpec(provider=provider, model="test-model")


def test_missing_api_key_raises() -> None:
    factory = LLMFactory(api_keys={LLMProvider.OPENAI: None})
    with pytest.raises(LLMProviderError, match="No API key configured"):
        factory.create(_spec())


def test_create_dispatches_to_builder_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[ModelSpec] = []

    def fake_builder(spec: ModelSpec, api_key: SecretStr) -> _StubChatModel:
        calls.append(spec)
        assert api_key.get_secret_value() == "k"
        return _StubChatModel(spec)

    factory = LLMFactory(api_keys={LLMProvider.OPENAI: SecretStr("k")})
    monkeypatch.setitem(factory._builders, LLMProvider.OPENAI, fake_builder)  # type: ignore[index]

    spec = _spec()
    first = factory.create(spec)
    second = factory.create(spec)

    assert first is second  # cached: one instance for identical specs
    assert len(calls) == 1  # builder invoked exactly once


def test_distinct_specs_build_distinct_models(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_builder(spec: ModelSpec, api_key: SecretStr) -> _StubChatModel:
        return _StubChatModel(spec)

    factory = LLMFactory(api_keys={LLMProvider.OPENAI: SecretStr("k")})
    monkeypatch.setitem(factory._builders, LLMProvider.OPENAI, fake_builder)  # type: ignore[index]

    a = factory.create(ModelSpec(provider=LLMProvider.OPENAI, model="m1"))
    b = factory.create(ModelSpec(provider=LLMProvider.OPENAI, model="m2"))
    assert a is not b


def test_reasoning_model_detection() -> None:
    """reasoning_format is valid only for reasoning models; llama/gemma reject it."""
    from synapse.infrastructure.llm_factory import _is_groq_reasoning_model

    assert _is_groq_reasoning_model("openai/gpt-oss-120b")
    assert _is_groq_reasoning_model("qwen/qwen3-32b")
    assert not _is_groq_reasoning_model("meta-llama/llama-4-scout-17b-16e-instruct")
    assert not _is_groq_reasoning_model("llama-3.3-70b-versatile")
    assert not _is_groq_reasoning_model("gemma-4-31b-it")
