"""SMTP-over-SSL send service.

Sends mail on the user's behalf via SMTP over an implicit-TLS (SSL) connection,
authenticating with a Gmail App Password (per the design's separation of read via
API and send via SMTP). The blocking ``smtplib`` exchange runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeEmailMessage

from pydantic import SecretStr

from synapse.errors import AuthenticationError, ExternalServiceError
from synapse.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SmtpConfig:
    """Connection and credential settings for the SMTP sender."""

    host: str
    port: int
    username: str
    app_password: SecretStr


def normalise_app_password(password: str) -> str:
    """Strip the display spacing from a Google App Password.

    Google shows App Passwords grouped as ``abcd efgh ijkl mnop``, and that is
    what users copy. The spaces are presentation only — the credential is the
    16 characters. Sending them verbatim fails authentication with a misleading
    "Username and Password not accepted", so they are removed here.
    """
    return "".join(password.split())


class SmtpService:
    """Sends email via SMTP over SSL (``MailSender``)."""

    def __init__(self, config: SmtpConfig) -> None:
        self._config = config

    async def send(self, *, to: str, subject: str, body: str) -> None:
        """Send an email; raises on transport or authentication failure."""
        try:
            await asyncio.to_thread(self._send_blocking, to, subject, body)
        except (AuthenticationError, ExternalServiceError):
            raise
        except smtplib.SMTPAuthenticationError as exc:
            raise AuthenticationError(f"SMTP authentication failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - normalise transport errors
            raise ExternalServiceError(f"Failed to send email: {exc}") from exc
        logger.info("email_sent", to=to, subject=subject)

    def _send_blocking(self, to: str, subject: str, body: str) -> None:
        message = MimeEmailMessage()
        message["From"] = self._config.username
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        password = normalise_app_password(self._config.app_password.get_secret_value())
        with smtplib.SMTP_SSL(self._config.host, self._config.port) as server:
            server.login(self._config.username, password)
            server.send_message(message)
