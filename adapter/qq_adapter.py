"""
qq_adapter.py – Full async QQ Official Bot WebSocket adapter.

QQ Gateway WebSocket protocol summary
--------------------------------------
op | name         | direction | description
---+--------------+-----------+--------------------------------
 0 | Dispatch     | recv      | Server pushes an event (t, d)
 1 | Heartbeat    | send      | Client keeps the connection alive
 2 | Identify     | send      | Client authenticates
 7 | Reconnect    | recv      | Server asks client to reconnect
 9 | InvalidSession| recv     | Identify was rejected
10 | Hello        | recv      | Server sends heartbeat_interval
11 | HeartbeatACK | recv      | Server acknowledges heartbeat

Reconnect / resume strategy
-----------------------------
If the server sends op=7 (Reconnect) we do a full restart (not a resume)
because a true Resume requires storing and replaying the sequence number –
this simpler strategy is safe and sufficient for most adapters.
"""

import asyncio
import json
import logging

import aiohttp

from .api_client import APIClient
from .auth import Auth
from .event_handler import EventHandler

logger = logging.getLogger(__name__)

# WebSocket opcode constants
_OP_DISPATCH = 0
_OP_HEARTBEAT = 1
_OP_IDENTIFY = 2
_OP_RECONNECT = 7
_OP_INVALID_SESSION = 9
_OP_HELLO = 10
_OP_HEARTBEAT_ACK = 11

# Seconds to wait before attempting a reconnect after a failure.
_RECONNECT_DELAY = 5


class QQAdapter:
    """
    Long-running async adapter that:
      1. Fetches an AccessToken via Auth.
      2. Retrieves the WebSocket gateway URL via APIClient.
      3. Opens an aiohttp WebSocket connection.
      4. Manages the heartbeat loop.
      5. Dispatches incoming events to EventHandler.
      6. Automatically reconnects on error.
    """

    def __init__(
        self,
        auth: Auth,
        api_client: APIClient,
        event_handler: EventHandler,
        intents: int,
    ):
        self.auth = auth
        self.api_client = api_client
        self.event_handler = event_handler
        self.intents = intents

        self._heartbeat_interval: float = 41_250 / 1_000  # default 41.25 s
        self._heartbeat_task: asyncio.Task | None = None
        self._sequence: int | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Public entry-point
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the adapter and keep it running until cancelled."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                logger.info("Adapter cancelled, shutting down.")
                self._running = False
                break
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "WebSocket error: %s – reconnecting in %s s",
                    exc,
                    _RECONNECT_DELAY,
                )
                await asyncio.sleep(_RECONNECT_DELAY)

    # ------------------------------------------------------------------
    # Internal – connection lifecycle
    # ------------------------------------------------------------------

    async def _connect_and_listen(self) -> None:
        gateway_url = await self.api_client.get_gateway_url()
        logger.info("Connecting to gateway: %s", gateway_url)

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(gateway_url) as ws:
                logger.info("WebSocket connection established.")
                await self._message_loop(ws)

    async def _message_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Receive and dispatch messages from the WebSocket."""
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self._handle_raw(ws, msg.data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error("WebSocket error frame received.")
                break
            elif msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                logger.warning(
                    "WebSocket closed (code=%s reason=%s).",
                    ws.close_code,
                    ws.exception(),
                )
                break

        # Cancel heartbeat when the connection drops.
        self._cancel_heartbeat()

    # ------------------------------------------------------------------
    # Internal – message handling
    # ------------------------------------------------------------------

    async def _handle_raw(
        self, ws: aiohttp.ClientWebSocketResponse, raw: str
    ) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Received non-JSON frame: %r", raw)
            return

        op: int = payload.get("op", -1)
        data = payload.get("d")
        event_type: str | None = payload.get("t")
        seq: int | None = payload.get("s")

        if seq is not None:
            self._sequence = seq

        if op == _OP_HELLO:
            await self._on_hello(ws, data)
        elif op == _OP_DISPATCH:
            await self._on_dispatch(event_type, data)
        elif op == _OP_HEARTBEAT_ACK:
            logger.debug("Heartbeat ACK received.")
        elif op == _OP_RECONNECT:
            logger.info("Server requested reconnect (op=7).")
            await ws.close()
        elif op == _OP_INVALID_SESSION:
            logger.warning("Invalid session (op=9). Reconnecting…")
            await ws.close()
        else:
            logger.debug("Unhandled op=%s payload: %s", op, payload)

    async def _on_hello(
        self, ws: aiohttp.ClientWebSocketResponse, data: dict
    ) -> None:
        interval_ms: int = data.get("heartbeat_interval", 41_250)
        self._heartbeat_interval = interval_ms / 1_000
        logger.info("Hello received, heartbeat_interval=%s ms", interval_ms)

        # Cancel any pre-existing heartbeat task before creating a new one.
        self._cancel_heartbeat()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))

        await self._identify(ws)

    async def _on_dispatch(
        self, event_type: str | None, data: dict | None
    ) -> None:
        if event_type is None or data is None:
            return
        await self.event_handler.handle_event(event_type, data)

    # ------------------------------------------------------------------
    # Internal – heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_loop(
        self, ws: aiohttp.ClientWebSocketResponse
    ) -> None:
        """Send a Heartbeat (op=1) every *heartbeat_interval* seconds."""
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            heartbeat = json.dumps({"op": _OP_HEARTBEAT, "d": self._sequence})
            try:
                await ws.send_str(heartbeat)
                logger.debug("Heartbeat sent (seq=%s).", self._sequence)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to send heartbeat: %s", exc)
                break

    def _cancel_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

    # ------------------------------------------------------------------
    # Internal – identify
    # ------------------------------------------------------------------

    async def _identify(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        token = await self.auth.get_access_token()
        identify_payload = {
            "op": _OP_IDENTIFY,
            "d": {
                "token": f"QQBot {token}",
                "intents": self.intents,
                "shard": [0, 1],
            },
        }
        await ws.send_str(json.dumps(identify_payload))
        logger.info("Identify sent (intents=%s).", self.intents)
