"""Worker agent definition and construction.

A worker is a stateless ReAct agent that reasons over its own tool set only. A
:class:`WorkerSpec` is the declarative description of one worker — its routing
name, the one-line capability the Manager sees, its system prompt, its tools, and
which model it runs on. :func:`build_worker_agent` turns a spec plus a chat model
into a compiled agent ready to register with the supervisor.

Workers are compiled WITHOUT a checkpointer: only the Manager owns conversation
memory, and each worker receives everything it needs in the Manager's delegated
instruction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool

from synapse.config.settings import ModelSpec

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


@dataclass(frozen=True)
class WorkerSpec:
    """Declarative definition of a worker agent.

    Attributes:
        name: The agent's unique name; also the suffix of its handoff tool
            (``transfer_to_<name>``). Use snake_case.
        description: One-line capability summary shown to the Manager in its
            roster, used to decide when to route here.
        prompt: The worker's deterministic system prompt.
        tools: The tools this worker may use — and the only capabilities it has.
        model_spec: The model this worker runs on.
    """

    name: str
    description: str
    prompt: str
    tools: Sequence[BaseTool]
    model_spec: ModelSpec


def build_worker_agent(spec: WorkerSpec, model: BaseChatModel) -> CompiledStateGraph:
    """Build a compiled ReAct worker agent from ``spec`` and its ``model``.

    Args:
        spec: The worker definition.
        model: The chat model instance the worker reasons with (already resolved
            from ``spec.model_spec`` by the caller, via the LLM factory).

    Returns:
        The compiled agent, named ``spec.name``, ready to pass to the supervisor.
    """
    return create_agent(
        model=model,
        tools=list(spec.tools),
        system_prompt=spec.prompt,
        name=spec.name,
    )
