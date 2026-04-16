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

        支持文本、图片、表情包等多种格式回复。
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

            # 🔴 改为提取完整的消息段而不仅仅是文本
            segments = MessageConverter.maibot_reply_to_segments(
                message_dict.get("message_segment") or {}
            )
            if not segments:
                logger.debug("MaiBot reply has no content, skipping.")
                return

            await self._deliver_reply(context, segments)
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Failed to parse MaiBot reply: %s", exc, exc_info=True)


    async def _deliver_reply(self, context: dict, segments: list) -> None:
        """
        Send reply to QQ with support for text, images, emojis, etc.

        参考 Napcat-Adapter 的实现方式。
        """
        msg_type = context["type"]
        original: Any = context["message"]

        try:
            # 🔴 转换为 QQ botpy 的消息格式
            qq_message_parts = []

            for seg in segments:
                seg_type = seg.get("type", "")
                data = seg.get("data", "")

                if seg_type == "text":
                    qq_message_parts.append({"type": "text", "data": data})

                elif seg_type == "image":
                    # URL 或 base64
                    qq_message_parts.append({"type": "image", "data": data})

                elif seg_type == "emoji":
                    # 表情包也转成图片
                    qq_message_parts.append({"type": "image", "data": data})

                elif seg_type == "voice":
                    # 语音
                    qq_message_parts.append({"type": "record", "data": data})

            if not qq_message_parts:
                logger.debug("No content to send.")
                return

            logger.info(f"📤 Sending reply with {len(qq_message_parts)} segments")

            # 🔴 发送到 QQ
            if msg_type == "guild":
                await original.reply(content=qq_message_parts)
            elif msg_type == "group":
                await original.reply(content=qq_message_parts, msg_type=0)
            elif msg_type == "c2c":
                await original.reply(content=qq_message_parts, msg_type=0)
            elif msg_type == "direct":
                await original.reply(content=qq_message_parts)
            else:
                logger.error("Unknown context type: %s", msg_type)

            logger.info("✅ Reply sent successfully")

        except Exception as exc:
            logger.error(
                "Failed to deliver reply (type=%s): %s", msg_type, exc, exc_info=True
            )
            # 降级：如果发送失败，至少发送文本
            try:
                fallback_text = " ".join(
                    seg.get("data", "")
                    for seg in segments
                    if seg.get("type") == "text"
                )
                if fallback_text:
                    logger.info("⚠️ Fallback: sending text only")
                    if msg_type == "guild":
                        await original.reply(content=fallback_text)
                    elif msg_type == "group":
                        await original.reply(content=fallback_text, msg_type=0)
                    elif msg_type == "c2c":
                        await original.reply(content=fallback_text, msg_type=0)
                    elif msg_type == "direct":
                        await original.reply(content=fallback_text)
            except Exception as fallback_exc:
                logger.error("Fallback text send also failed: %s", fallback_exc)
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
