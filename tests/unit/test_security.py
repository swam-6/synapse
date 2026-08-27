"""Unit tests for webhook secret-token verification."""

from __future__ import annotations

from pydantic import SecretStr

from synapse.api.security import verify_secret_token


def test_no_expected_secret_accepts_any_request() -> None:
    assert verify_secret_token(None, None) is True
    assert verify_secret_token("anything", None) is True


def test_matching_token_passes() -> None:
    assert verify_secret_token("s3cret", SecretStr("s3cret")) is True


def test_mismatched_token_fails() -> None:
    assert verify_secret_token("wrong", SecretStr("s3cret")) is False


def test_missing_token_when_required_fails() -> None:
    assert verify_secret_token(None, SecretStr("s3cret")) is False
