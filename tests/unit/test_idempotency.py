"""Unit tests for the webhook idempotency guard."""

from __future__ import annotations

import pytest

from synapse.api.idempotency import IdempotencyGuard


@pytest.mark.asyncio
async def test_first_sighting_is_new_then_duplicate() -> None:
    guard = IdempotencyGuard(max_entries=10)
    assert await guard.seen(1001) is False
    assert await guard.seen(1001) is True


@pytest.mark.asyncio
async def test_distinct_ids_are_independent() -> None:
    guard = IdempotencyGuard(max_entries=10)
    assert await guard.seen(1) is False
    assert await guard.seen(2) is False


@pytest.mark.asyncio
async def test_oldest_entry_is_evicted_beyond_capacity() -> None:
    guard = IdempotencyGuard(max_entries=2)
    await guard.seen(1)
    await guard.seen(2)
    await guard.seen(3)  # evicts id 1 (oldest)
    assert await guard.seen(1) is False  # seen again as new after eviction


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        IdempotencyGuard(max_entries=0)
