"""A scripted chat model and factory for deterministic, key-free agent tests.

``ScriptedChatModel`` returns a fixed sequence of pre-authored ``AIMessage``
responses (optionally carrying tool calls), so a full supervisor -> worker ->
supervisor delegation cycle can be driven without any real LLM or API key.
``ScriptedModelFactory`` hands out models in call order, matching the order in
which :func:`synapse.agents.manager.build_manager_graph` resolves the Manager and
then each worker.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from synapse.config.settings import ModelSpec


class ScriptedChatModel(BaseChatModel):
    """A chat model that replays a fixed list of responses in order."""

    responses: list[AIMessage]
    index: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        current = self.index
        message = (
            self.responses[current]
            if current < len(self.responses)
            else AIMessage(content="(script exhausted)")
        )
        object.__setattr__(self, "index", current + 1)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        # The script is fixed regardless of bound tools.
        return self


def tool_call(name: str, call_id: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a tool-call dict for embedding in a scripted ``AIMessage``."""
    return {"name": name, "args": args or {}, "id": call_id, "type": "tool_call"}


class ScriptedModelFactory:
    """A :class:`ChatModelProvider` returning scripted models in call order."""

    def __init__(self, models: list[ScriptedChatModel]) -> None:
        self._models = models
        self._calls = 0

    def create(self, spec: ModelSpec) -> BaseChatModel:
        model = self._models[self._calls]
        self._calls += 1
        return model
