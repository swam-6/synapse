"""Unit tests for the SMTP send service with smtplib mocked (no network)."""

from __future__ import annotations

import smtplib

import pytest
from pydantic import SecretStr

from synapse.errors import AuthenticationError, ExternalServiceError
from synapse.services.email.smtp import SmtpConfig, SmtpService


class _FakeSMTPSSL:
    """Records login/send_message calls; used as a context manager."""

    instances: list["_FakeSMTPSSL"] = []

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.logged_in: tuple[str, str] | None = None
        self.sent_message = None
        _FakeSMTPSSL.instances.append(self)

    def __enter__(self) -> "_FakeSMTPSSL":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        self.logged_in = (username, password)

    def send_message(self, message: object) -> None:
        self.sent_message = message


def _config() -> SmtpConfig:
    return SmtpConfig(
        host="smtp.example.com", port=465, username="me@example.com",
        app_password=SecretStr("app-pass"),
    )


@pytest.mark.asyncio
async def test_send_constructs_and_transmits_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSMTPSSL.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTPSSL)

    await SmtpService(_config()).send(to="you@example.com", subject="Hi", body="Hello")

    assert len(_FakeSMTPSSL.instances) == 1
    server = _FakeSMTPSSL.instances[0]
    assert server.host == "smtp.example.com" and server.port == 465
    assert server.logged_in == ("me@example.com", "app-pass")
    assert server.sent_message is not None
    assert server.sent_message["To"] == "you@example.com"
    assert server.sent_message["Subject"] == "Hi"
    assert server.sent_message["From"] == "me@example.com"


@pytest.mark.asyncio
async def test_auth_failure_maps_to_authentication_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise smtplib.SMTPAuthenticationError(535, b"bad creds")

    monkeypatch.setattr(smtplib, "SMTP_SSL", _raise)
    with pytest.raises(AuthenticationError):
        await SmtpService(_config()).send(to="you@example.com", subject="Hi", body="Hello")


@pytest.mark.asyncio
async def test_transport_failure_maps_to_external_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP_SSL", _raise)
    with pytest.raises(ExternalServiceError):
        await SmtpService(_config()).send(to="you@example.com", subject="Hi", body="Hello")


def test_app_password_display_spaces_are_stripped() -> None:
    """Google shows App Passwords as 'abcd efgh ijkl mnop'; users paste that."""
    from synapse.services.email.smtp import normalise_app_password

    assert normalise_app_password("abcd efgh ijkl mnop") == "abcdefghijklmnop"
    assert normalise_app_password("  abcd efgh ijkl mnop  ") == "abcdefghijklmnop"
    assert normalise_app_password("abcdefghijklmnop") == "abcdefghijklmnop"
