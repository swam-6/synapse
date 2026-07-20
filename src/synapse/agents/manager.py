"""Assembly of the Manager supervisor graph.

``build_manager_graph`` composes the full agentic graph: it resolves the Manager
and worker models from the LLM factory, constructs each worker agent, renders the
Manager prompt from the live worker roster, and wires them together with
``langgraph-supervisor``'s ``create_supervisor`` — whose auto-generated handoff
tools are the "SendMessage" delegation mechanism the design calls for. The
compiled graph is checkpointed so the Manager (and only the Manager) has
conversation memory.

Delegation is sequential (``parallel_tool_calls=False``) and ``output_mode`` is
``last_message`` so only each worker's final result — not its internal reasoning —
enters the Manager's context, keeping execution deterministic and the history
clean.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from langchain_core.messages import trim_messages
from langgraph_supervisor import create_forward_message_tool, create_supervisor

from synapse.agents.calendar import build_calendar_worker_spec
from synapse.agents.email import build_email_worker_spec
from synapse.agents.notion import build_notion_worker_spec
from synapse.agents.slack import build_slack_worker_spec
from synapse.agents.worker import WorkerSpec, build_worker_agent
from synapse.config.settings import AgentRole, Settings
from synapse.errors import ConfigurationError
from synapse.infrastructure.llm_factory import ChatModelProvider
from synapse.observability.logging import get_logger
from synapse.prompts.manager import build_manager_prompt

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph

logger = get_logger(__name__)

# The supervisor node name; also the graph node the channel's reply comes from.
SUPERVISOR_NAME = "supervisor"


#: Builders for every available worker, keyed by name.
_WORKER_BUILDERS = {
    "email": build_email_worker_spec,
    "calendar": build_calendar_worker_spec,
    "notion": build_notion_worker_spec,
    "slack": build_slack_worker_spec,
}


def _build_history_trimmer(max_tokens: int):
    """Return a ``pre_model_hook`` that caps the Manager's history per LLM call.

    The hook trims ``state["messages"]`` to the most recent ``max_tokens`` tokens
    and returns them as ``llm_input_messages`` — the trimmed view is what the
    model sees, but the full history is left untouched in the checkpoint, so
    conversation memory (and the final-reply extraction in ``run_turn``) is
    unaffected. Only the per-call input the provider is billed and rate-limited
    on shrinks.

    ``strategy="last"`` keeps the tail, so the in-flight turn is always retained
    and only older turns fall away. ``start_on="human"`` guarantees the trimmed
    window begins on a user message, never a dangling ``ToolMessage`` — the
    strict-provider (Groq) ordering rule that an aged thread must not violate.
    The approximate token counter is local and deterministic, adding no latency
    and no extra API call, and keeps the cache-friendly prompt prefix stable.
    """

    def _trim(state: dict[str, Any]) -> dict[str, Any]:
        trimmed = trim_messages(
            state["messages"],
            max_tokens=max_tokens,
            token_counter="approximate",
            strategy="last",
            start_on="human",
            include_system=False,
            allow_partial=False,
        )
        return {"llm_input_messages": trimmed}

    return _trim


def default_worker_specs(settings: Settings) -> list[WorkerSpec]:
    """Return the enabled specialist workers registered with the Manager.

    Which workers are built is controlled by ``settings.enabled_workers`` (all
    four — Email, Calendar, Notion, Slack — by default). Only enabled workers are
    constructed, so a deployment need only configure the integrations it uses.

    Raises:
        ConfigurationError: if no known worker is enabled (the supervisor needs
            at least one worker to delegate to).
    """
    enabled = settings.enabled_worker_names()
    specs = [
        _WORKER_BUILDERS[name](settings)
        for name in _WORKER_BUILDERS
        if name in enabled
    ]
    if not specs:
        raise ConfigurationError(
            "No workers are enabled. Set SYNAPSE_ENABLED_WORKERS to at least one "
            f"of: {', '.join(_WORKER_BUILDERS)}."
        )
    return specs


def build_manager_graph(
    checkpointer: BaseCheckpointSaver,
    *,
    llm_factory: ChatModelProvider,
    settings: Settings,
    worker_specs: Sequence[WorkerSpec] | None = None,
) -> CompiledStateGraph:
    """Build and compile the Manager supervisor graph.

    Args:
        checkpointer: Conversation-memory saver bound to the compiled graph.
        llm_factory: Provider of chat models for the Manager and each worker.
        settings: Application settings (drives per-role model resolution).
        worker_specs: Override the worker roster (used in tests). Defaults to
            :func:`default_worker_specs`.

    Returns:
        The compiled supervisor graph, invoked exactly like the Phase 1 skeleton
        (``ainvoke`` with a ``thread_id``), so the channel is unchanged.
    """
    specs = list(worker_specs) if worker_specs is not None else default_worker_specs(settings)

    # Resolve the Manager model first, then each worker's, so a call-ordered test
    # double can map scripted models deterministically.
    manager_model = llm_factory.create(settings.model_spec_for(AgentRole.MANAGER))
    agents = [build_worker_agent(spec, llm_factory.create(spec.model_spec)) for spec in specs]

    # A supervisor tool that forwards a worker's final message to the user
    # verbatim, skipping the Manager's own summarising LLM call — the largest
    # call of a turn (it carries the fullest history). Verbatim relay also
    # removes the paraphrase step that has twice dropped a worker's dates/times.
    max_history = settings.manager_history_max_tokens
    workflow = create_supervisor(
        agents=agents,
        model=manager_model,
        prompt=build_manager_prompt(specs),
        tools=[create_forward_message_tool(SUPERVISOR_NAME)],
        # Bound the Manager's ever-growing history per LLM call (None disables).
        pre_model_hook=_build_history_trimmer(max_history) if max_history else None,
        parallel_tool_calls=False,
        output_mode="last_message",
        supervisor_name=SUPERVISOR_NAME,
        # Do NOT persist "transfer back to supervisor" messages into history.
        # They contain a transfer_back_to_supervisor tool call that a worker is
        # not given as a tool; left in the thread, a worker model imitates the
        # pattern on a later turn and emits that phantom call, which strict
        # providers (Groq) reject with 400 tool_use_failed. Suppressing them is
        # why a fresh thread works but an aged one fails.
        add_handoff_back_messages=False,
    )
    logger.info(
        "manager_graph_built",
        workers=[spec.name for spec in specs],
        supervisor=SUPERVISOR_NAME,
    )
    return workflow.compile(checkpointer=checkpointer)
