"""
auth.py – Obtain and cache the QQ Official Bot AccessToken.

The token endpoint is:
  POST https://bots.qq.com/app/getAppAccessToken
  Body: {"appId": "<app_id>", "clientSecret": "<app_secret>"}
  Response: {"access_token": "...", "expires_in": 7200}
"""

import logging
import time

import aiohttp

logger = logging.getLogger(__name__)

# A small safety margin (seconds) before the token's stated expiry at which we
# proactively refresh it so callers never receive a stale token.
_EXPIRY_MARGIN = 60


class Auth:
    """Manages the QQ Bot AccessToken lifecycle."""

    def __init__(self, app_id: str, app_secret: str, auth_url: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.auth_url = auth_url

        self._access_token: str | None = None
        self._expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def is_expired(self) -> bool:
        """Return True if the cached token is absent or about to expire."""
        return self._access_token is None or time.time() >= self._expires_at

    async def get_access_token(self) -> str:
        """Return a valid AccessToken, refreshing it if necessary."""
        if self.is_expired:
            await self._refresh_token()
        return self._access_token  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _refresh_token(self) -> None:
        payload = {"appId": self.app_id, "clientSecret": self.app_secret}
        logger.debug("Fetching new AccessToken from %s", self.auth_url)

        async with aiohttp.ClientSession() as session:
            async with session.post(self.auth_url, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 7200))
        self._expires_at = time.time() + expires_in - _EXPIRY_MARGIN
        logger.info(
            "AccessToken refreshed, expires in %s seconds (effective margin %s s)",
            expires_in,
            _EXPIRY_MARGIN,
        )
