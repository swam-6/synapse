"""Slack integration: read channel/DM messages and send messages."""

from synapse.services.slack.models import SlackChannel, SlackMessage
from synapse.services.slack.protocols import SlackGateway
from synapse.services.slack.slack import SlackService

__all__ = ["SlackChannel", "SlackGateway", "SlackMessage", "SlackService"]
