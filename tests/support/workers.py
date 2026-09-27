"""A trivial, dependency-free worker spec for supervisor-wiring tests.

Delegation tests need *a* worker to route to, but must not depend on any real
service. This provides a minimal worker with one pure tool, so the supervisor
mechanics can be exercised in isolation.
"""

from __future__ import annotations

from langchain_core.tools import tool

from synapse.agents.worker import WorkerSpec
from synapse.config.settings import Settings

TEST_AGENT_NAME = "test_agent"


@tool
def echo_tool(text: str) -> str:
    """Echo the given text back (test-only tool)."""
    return text


def build_test_worker_spec(settings: Settings, *, name: str = TEST_AGENT_NAME) -> WorkerSpec:
    """Return a minimal worker spec using a single pure tool."""
    return WorkerSpec(
        name=name,
        description="Test worker used to exercise supervisor delegation.",
        prompt="You are a test worker. Use echo_tool when asked.",
        tools=[echo_tool],
        model_spec=settings.default_model_spec(),
    )
