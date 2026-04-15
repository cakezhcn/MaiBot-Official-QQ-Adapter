"""
qq_adapter.py – QQ Official Bot adapter based on the official qq-botpy library.

This module inherits from botpy.Client and handles all QQ message events,
forwarding them to MaiBot in maim_message format via the MaiBotClient.
It also receives MaiBot's replies and sends them back to QQ.

Supported message types:
  - Guild @-mention messages  (on_at_message_create)
  - Group @-mention messages  (on_group_at_message_create)
  - C2C private messages      (on_c2c_message_create)
  - Guild direct messages     (on_direct_message_create)
"""

import asyncio
import logging
from typing import Any

import botpy
from botpy.message import C2CMessage, DirectMessage, GroupMessage, Message

from .maibot_client import MaiBotClient
from .message_converter import MessageConverter

logger = logging.getLogger(__name__)

# How long (seconds) to wait after on_ready before failing a send attempt.
_CONNECT_TIMEOUT = 10


class QQOfficialBotAdapter(botpy.Client):
    """
    QQ Official Bot adapter using the botpy library.

    Responsibilities:
      1. Receive QQ events through botpy's WebSocket connection.
      2. Convert them to maim_message format and forward to MaiBot.
      3. Accept replies from MaiBot and send them back to QQ.
    """

    def __init__(self, maibot_client: "MaiBotClient", intents: botpy.Intents):
        super().__init__(intents=intents)
        self.maibot_client = maibot_client

        # Routing table: maps a "context key" (guild_id / group_openid /
        # user_openid) to the last received QQ message for that context.
        # Used to route MaiBot replies back to the correct QQ endpoint.
        self._reply_context: dict[str, Any] = {}

        # Background task that maintains the MaiBotClient connection.
        self._maibot_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # botpy lifecycle
    # ------------------------------------------------------------------

    async def on_ready(self):
        """Called when the bot successfully connects to QQ."""
        logger.info(
            "Bot is ready! Logged in as %s (app_id=%s).",
            self.robot.name,
            self.robot.id,
        )
        # Start the MaiBot client in a background task so it can receive
        # replies while we process new QQ events.
        self.maibot_client.set_reply_handler(self._handle_maibot_reply)
        self._maibot_task = asyncio.create_task(
            self.maibot_client.run(), name="maibot-client"
        )

    # ------------------------------------------------------------------
    # QQ event handlers
    # ------------------------------------------------------------------

    async def on_at_message_create(self, message: Message):
        """Guild channel @-mention message (public-domain bots)."""
        logger.info(
            "Guild @-mention from %s in channel %s: %s",
            message.author.username,
            message.channel_id,
            message.content[:100],
        )
        # Save routing context so replies can be delivered.
        self._reply_context[message.guild_id] = {
            "type": "guild",
            "message": message,
        }
        payload = MessageConverter.guild_message_to_maibot(message)
        await self._safe_send_to_maibot(payload)

    async def on_group_at_message_create(self, message: GroupMessage):
        """Group @-mention message."""
        logger.info(
            "Group @-mention from %s in group %s: %s",
            message.author.member_openid,
            message.group_openid,
            message.content[:100],
        )
        self._reply_context[message.group_openid] = {
            "type": "group",
            "message": message,
        }
        payload = MessageConverter.group_message_to_maibot(message)
        await self._safe_send_to_maibot(payload)

    async def on_c2c_message_create(self, message: C2CMessage):
        """C2C (private user) message."""
        logger.info(
            "C2C message from %s: %s",
            message.author.user_openid,
            message.content[:100],
        )
        self._reply_context[message.author.user_openid] = {
            "type": "c2c",
            "message": message,
        }
        payload = MessageConverter.c2c_message_to_maibot(message)
        await self._safe_send_to_maibot(payload)

    async def on_direct_message_create(self, message: DirectMessage):
        """Guild direct (private) message."""
        logger.info(
            "Direct message from %s in guild %s: %s",
            message.author.id,
            message.guild_id,
            message.content[:100],
        )
        self._reply_context[message.guild_id] = {
            "type": "direct",
            "message": message,
        }
        payload = MessageConverter.direct_message_to_maibot(message)
        await self._safe_send_to_maibot(payload)

    # ------------------------------------------------------------------
    # MaiBot reply handler
    # ------------------------------------------------------------------

    async def _handle_maibot_reply(self, message_dict: dict) -> None:
        """
        Called by MaiBotClient when MaiBot sends a reply.

        Looks up the matching QQ context and delivers the reply.
        """
        try:
            message_info = message_dict.get("message_info") or {}
            group_info = message_info.get("group_info") or {}
            group_id: str = group_info.get("group_id", "")

            context = self._reply_context.get(group_id)
            if not context:
                logger.warning(
                    "No routing context found for group_id=%s – dropping reply.",
                    group_id,
                )
                return

            reply_text = MessageConverter.maibot_reply_to_text(
                message_dict.get("message_segment") or {}
            )
            if not reply_text:
                logger.debug("MaiBot reply has no text content, skipping.")
                return

            await self._deliver_reply(context, reply_text)
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Failed to parse MaiBot reply: %s", exc, exc_info=True)

    async def _deliver_reply(self, context: dict, text: str) -> None:
        """Send *text* to QQ using the routing context."""
        msg_type = context["type"]
        original: Any = context["message"]
        try:
            if msg_type == "guild":
                await original.reply(content=text)
            elif msg_type == "group":
                await original.reply(content=text, msg_type=0)
            elif msg_type == "c2c":
                await original.reply(content=text, msg_type=0)
            elif msg_type == "direct":
                await original.reply(content=text)
            else:
                logger.error("Unknown context type: %s", msg_type)
        except (ConnectionError, OSError, RuntimeError) as exc:
            logger.error(
                "Failed to deliver reply (type=%s): %s", msg_type, exc, exc_info=True
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _safe_send_to_maibot(self, payload: dict) -> None:
        """Forward *payload* to MaiBot, waiting for the connection if needed."""
        deadline = asyncio.get_event_loop().time() + _CONNECT_TIMEOUT
        while not self.maibot_client.is_connected():
            if asyncio.get_event_loop().time() >= deadline:
                logger.error(
                    "MaiBot client not connected after %s s – dropping message.",
                    _CONNECT_TIMEOUT,
                )
                return
            await asyncio.sleep(0.5)

        ok = await self.maibot_client.send_message(payload)
        if not ok:
            logger.warning("MaiBot client reported send failure.")
