"""
event_handler.py – Dispatch QQ WebSocket events and forward messages to MaiBot.

Supported events:
  READY                – session established
  MESSAGE_CREATE       – new channel message (private-domain bots)
  AT_MESSAGE_CREATE    – @-mention message (public-domain bots)
  DIRECT_MESSAGE_CREATE– direct / private message
"""

import logging

import aiohttp

from .message_converter import MessageConverter

logger = logging.getLogger(__name__)

# Events that carry a chat message payload we want to forward to MaiBot.
_MESSAGE_EVENTS = {"MESSAGE_CREATE", "AT_MESSAGE_CREATE", "DIRECT_MESSAGE_CREATE"}


class EventHandler:
    """Route incoming QQ events to the appropriate handler."""

    def __init__(self, maibot_url: str):
        self.maibot_url = maibot_url

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    async def handle_event(self, event_type: str, event_data: dict) -> None:
        """Dispatch an event by its *event_type* string."""
        if event_type == "READY":
            self._on_ready(event_data)
        elif event_type in _MESSAGE_EVENTS:
            await self._on_message(event_type, event_data)
        else:
            logger.debug("Unhandled event type: %s", event_type)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_ready(self, data: dict) -> None:
        user = data.get("user", {})
        logger.info(
            "Bot is ready! Logged in as %s (id=%s)",
            user.get("username", "unknown"),
            user.get("id", "unknown"),
        )

    async def _on_message(self, event_type: str, data: dict) -> None:
        maibot_payload = MessageConverter.qq_event_to_maibot(data)
        logger.info(
            "===== New message (%s) =====\n"
            "  user:    %s (%s)\n"
            "  guild:   %s  channel: %s\n"
            "  content: %s",
            event_type,
            maibot_payload["user_name"],
            maibot_payload["user_id"],
            maibot_payload["guild_id"],
            maibot_payload["channel_id"],
            maibot_payload["content"],
        )

        await self._forward_to_maibot(maibot_payload)

    # ------------------------------------------------------------------
    # MaiBot integration
    # ------------------------------------------------------------------

    async def _forward_to_maibot(self, payload: dict) -> None:
        """POST the converted message payload to MaiBot."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.maibot_url, json=payload) as resp:
                    if resp.status == 200:
                        logger.debug(
                            "Message forwarded to MaiBot (status=%s)", resp.status
                        )
                    else:
                        body = await resp.text()
                        logger.warning(
                            "MaiBot returned non-200 status %s: %s",
                            resp.status,
                            body,
                        )
        except aiohttp.ClientError as exc:
            logger.error("Failed to forward message to MaiBot: %s", exc)
