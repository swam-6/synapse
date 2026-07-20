"""Human-in-the-loop approval for side-effecting tools.

Outbound actions (sending email, creating events/tasks, posting to Slack) are
irreversible, so they are gated behind a LangGraph ``interrupt``: when the worker
invokes such a tool, execution pauses and a confirmation request is surfaced to
the user through the Manager's reply. The user's next message resumes the graph;
the tool runs only if that reply is affirmative, otherwise it is cancelled.

``with_approval`` wraps a tool so its schema, name, and description are preserved
while an approval gate is inserted before the underlying action. This keeps the
approval concern out of both the tools (which stay pure wrappers) and the
services (which stay pure I/O).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt

from synapse.observability.logging import get_logger

logger = get_logger(__name__)

# Single words that, when they LEAD the reply, count as approval — so natural
# phrasing like "yes please" or "sure, go for it" is recognised, not just "yes".
_AFFIRMATIVE_WORDS = frozenset(
    {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "approve", "approved",
     "confirm", "confirmed", "proceed", "send", "true", "1"}
)
# Leading words that always mean rejection, checked first so "no, do it" is a
# clear "no" rather than being tripped by a later affirmative word.
_NEGATIVE_WORDS = frozenset(
    {"no", "n", "nope", "nah", "cancel", "stop", "don't", "dont", "never", "false", "0"}
)
# Multi-word affirmatives whose first word is ambiguous on its own ("do", "go").
_AFFIRMATIVE_PHRASES = frozenset({"go ahead", "do it", "go for it", "yes please"})

# Punctuation stripped before matching, so "yes!" / "yes." / "yes," all count.
_STRIP = " \t\n.,!?:;\"'"


def is_affirmative(decision: Any) -> bool:
    """Interpret a resume value as approval (``True``) or rejection (``False``).

    Approval must be *explicit*: the reply must lead with an affirmative word (or
    be a known affirmative phrase). Anything unrecognised — including a brand-new
    request typed instead of a yes/no — is treated as rejection, so an ambiguous
    answer never triggers an irreversible action.
    """
    if isinstance(decision, bool):
        return decision
    if isinstance(decision, dict):
        for key in ("approved", "approve", "confirm"):
            if key in decision:
                return bool(decision[key])
        decision = decision.get("text", "")

    normalised = str(decision).strip(_STRIP).lower()
    if not normalised:
        return False
    if normalised in _AFFIRMATIVE_PHRASES:
        return True
    first_word = normalised.split()[0].strip(_STRIP)
    if first_word in _NEGATIVE_WORDS:
        return False
    return first_word in _AFFIRMATIVE_WORDS


@dataclass(frozen=True)
class ApprovalPolicy:
    """Marks a tool as requiring approval and how to describe the pending action.

    Attributes:
        tool_name: The name of the tool to gate.
        summarize: Builds a one-line, user-facing description of the action from
            the tool's call arguments (e.g. "Send an email to a@b.com?").
    """

    tool_name: str
    summarize: Callable[[dict[str, Any]], str]


def with_approval(tool: BaseTool, summarize: Callable[[dict[str, Any]], str]) -> BaseTool:
    """Return a copy of ``tool`` that requires user approval before running."""

    async def _gated(**kwargs: Any) -> Any:
        summary = summarize(kwargs)
        decision = interrupt(
            {"type": "approval_request", "action": tool.name, "summary": summary, "arguments": kwargs}
        )
        if not is_affirmative(decision):
            logger.info("action_rejected", action=tool.name)
            return f"The action was cancelled by the user: {summary}"
        logger.info("action_approved", action=tool.name)
        return await tool.ainvoke(kwargs)

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=_gated,
    )


def apply_approvals(
    tools: Sequence[BaseTool], policies: Sequence[ApprovalPolicy], *, enabled: bool
) -> list[BaseTool]:
    """Wrap the tools named by ``policies`` with approval gates when ``enabled``.

    Tools without a matching policy pass through unchanged. When ``enabled`` is
    false (e.g. a trusted/batch deployment) all tools pass through unchanged.
    """
    if not enabled:
        return list(tools)
    by_name = {policy.tool_name: policy for policy in policies}
    return [
        with_approval(tool, by_name[tool.name].summarize) if tool.name in by_name else tool
        for tool in tools
    ]
