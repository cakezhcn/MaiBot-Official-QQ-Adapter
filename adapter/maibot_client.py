"""
maibot_client.py – Async client for communicating with MaiBot.

Uses maim_message.MessageClient (WebSocket mode) to:
  1. Connect to MaiBot's message server.
  2. Forward QQ messages to MaiBot.
  3. Receive replies from MaiBot and dispatch them to a registered handler.
"""

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from maim_message import MessageClient

logger = logging.getLogger(__name__)

# Seconds between reconnect attempts when the connection is lost.
_RECONNECT_DELAY = 5


class MaiBotClient:
    """
    Thin wrapper around maim_message.MessageClient that adds:
      - Automatic reconnection.
      - A simple callback interface for incoming replies.
    """

    def __init__(
        self,
        server_url: str,
        platform: str = "qq_official",
        token: Optional[str] = None,
    ):
        """
        Args:
            server_url: WebSocket URL of MaiBot's message server,
                        e.g. ``ws://localhost:8080/ws``.
            platform:   Platform identifier sent to MaiBot.
            token:      Optional auth token for MaiBotServer.
        """
        self.server_url = server_url
        self.platform = platform
        self.token = token

        self._client: MessageClient = MessageClient(mode="ws")
        self._reply_handler: Optional[Callable[[dict], Awaitable[None]]] = None
        self._connected = False

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_reply_handler(
        self, handler: Callable[[dict], Awaitable[None]]
    ) -> None:
        """Register *handler* to be called when MaiBot sends a reply."""
        self._reply_handler = handler

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Connect to MaiBot and keep the connection alive indefinitely."""
        while True:
            try:
                await self._connect()
                await self._client.run()
            except asyncio.CancelledError:
                logger.info("MaiBotClient task cancelled.")
                self._connected = False
                raise
            except (ConnectionError, OSError, TimeoutError) as exc:
                self._connected = False
                logger.error(
                    "MaiBotClient connection error: %s – reconnecting in %s s",
                    exc,
                    _RECONNECT_DELAY,
                )
                await asyncio.sleep(_RECONNECT_DELAY)
            except Exception as exc:
                self._connected = False
                logger.error(
                    "MaiBotClient unexpected error: %s – reconnecting in %s s",
                    exc,
                    _RECONNECT_DELAY,
                    exc_info=True,
                )
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _connect(self) -> None:
        """Establish the WebSocket connection and register the message handler."""
        self._client = MessageClient(mode="ws")
        self._client.register_message_handler(self._on_message_from_maibot)
        logger.info("Connecting to MaiBot at %s (platform=%s)…", self.server_url, self.platform)
        await self._client.connect(
            url=self.server_url,
            platform=self.platform,
            token=self.token,
        )
        self._connected = True
        logger.info("Connected to MaiBot successfully.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return True if currently connected to MaiBot."""
        return self._connected and self._client.is_connected()

    async def send_message(self, message_dict: dict) -> bool:
        """
        Send *message_dict* (maim_message format) to MaiBot.

        Returns True on success, False on failure.
        """
        if not self.is_connected():
            logger.warning("Cannot send message – not connected to MaiBot.")
            return False
        try:
            return await self._client.send_message(message_dict)
        except (ConnectionError, OSError, RuntimeError) as exc:
            logger.error("Failed to send message to MaiBot: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _on_message_from_maibot(self, message_dict: dict) -> None:
        """Callback invoked when MaiBot sends a message to this adapter."""
        logger.debug("Received message from MaiBot: %s", str(message_dict)[:200])
        if self._reply_handler is not None:
            try:
                await self._reply_handler(message_dict)
            except (KeyError, TypeError, ValueError) as exc:
                logger.error(
                    "Reply handler raised a parsing error: %s", exc, exc_info=True
                )
            except Exception as exc:
                logger.error(
                    "Reply handler raised an unexpected error: %s", exc, exc_info=True
                )
        else:
            logger.debug("No reply handler registered – discarding MaiBot message.")
