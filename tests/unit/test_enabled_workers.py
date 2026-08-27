"""Unit tests for the enabled-workers roster toggle."""

from __future__ import annotations

import pytest

from synapse.config.settings import Settings
from synapse.errors import ConfigurationError


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_default_enables_all_four() -> None:
    assert _settings().enabled_worker_names() == ["email", "calendar", "notion", "slack"]


def test_subset_is_parsed_and_normalised() -> None:
    assert _settings(enabled_workers=" Calendar , email ").enabled_worker_names() == [
        "calendar",
        "email",
    ]


def test_no_enabled_workers_raises_in_default_specs() -> None:
    # Import here so the module-level builders resolve after settings exist.
    from synapse.agents.manager import default_worker_specs

    with pytest.raises(ConfigurationError, match="No workers are enabled"):
        default_worker_specs(_settings(enabled_workers=""))
