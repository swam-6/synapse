"""Unit tests for the per-chat fixed-window rate limiter."""

from __future__ import annotations

import pytest

from synapse.api.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_allows_up_to_budget_then_blocks() -> None:
    limiter = RateLimiter(max_events=2, window_seconds=60.0)
    assert await limiter.allow("chat") is True
    assert await limiter.allow("chat") is True
    assert await limiter.allow("chat") is False


@pytest.mark.asyncio
async def test_budgets_are_per_key() -> None:
    limiter = RateLimiter(max_events=1, window_seconds=60.0)
    assert await limiter.allow("a") is True
    assert await limiter.allow("b") is True  # different key, own budget
    assert await limiter.allow("a") is False


@pytest.mark.asyncio
async def test_window_resets_after_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(
        "synapse.api.rate_limit.time.monotonic", lambda: clock["now"]
    )
    limiter = RateLimiter(max_events=1, window_seconds=10.0)
    assert await limiter.allow("chat") is True
    assert await limiter.allow("chat") is False
    clock["now"] = 11.0
    assert await limiter.allow("chat") is True  # fresh window


def test_invalid_parameters_rejected() -> None:
    with pytest.raises(ValueError):
        RateLimiter(max_events=0)
    with pytest.raises(ValueError):
        RateLimiter(window_seconds=0)
