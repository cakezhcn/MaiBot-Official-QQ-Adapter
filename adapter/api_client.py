"""
api_client.py – Thin async wrapper around the QQ Official Bot REST API.

Responsibilities:
  • Fetch the WebSocket gateway URL.
  • Send a reply message to a channel (used by EventHandler after AI processing).
"""

import logging

import aiohttp

from .auth import Auth

logger = logging.getLogger(__name__)


class APIClient:
    """Async client for the QQ Official Bot REST API."""

    def __init__(self, auth: Auth, api_base_url: str):
        self.auth = auth
        self.api_base_url = api_base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _auth_headers(self) -> dict:
        token = await self.auth.get_access_token()
        return {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Gateway
    # ------------------------------------------------------------------

    async def get_gateway_url(self) -> str:
        """Return the WebSocket gateway URL for this bot."""
        headers = await self._auth_headers()
        url = f"{self.api_base_url}/gateway/bot"
        logger.debug("Fetching WebSocket gateway URL from %s", url)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()

        gateway_url: str = data["url"]
        logger.info("WebSocket gateway URL: %s", gateway_url)
        return gateway_url

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_channel_message(
        self,
        channel_id: str,
        content: str,
        msg_id: str | None = None,
    ) -> dict:
        """Send a text message to a channel, optionally quoting *msg_id*."""
        headers = await self._auth_headers()
        url = f"{self.api_base_url}/channels/{channel_id}/messages"
        payload: dict = {"content": content}
        if msg_id:
            payload["msg_id"] = msg_id

        logger.debug("Sending message to channel %s: %s", channel_id, content)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                result: dict = await resp.json()
        return result
