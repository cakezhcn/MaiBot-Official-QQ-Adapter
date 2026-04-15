"""
message_converter.py – Convert messages between the QQ Official Bot event
format and the payload shape that MaiBot expects (and returns).

QQ event payload shape (simplified):
{
  "id": "<message_id>",
  "channel_id": "<channel_id>",
  "guild_id": "<guild_id>",
  "content": "<text, may contain @<@!bot_id> prefix>",
  "timestamp": "2024-01-01T00:00:00+08:00",
  "author": {
    "id": "<user_id>",
    "username": "<username>",
    "avatar": "<avatar_url>"
  }
}

MaiBot message payload shape (sent via HTTP POST):
{
  "message_id": "<message_id>",
  "time": <unix_timestamp_int>,
  "message_type": "guild",
  "guild_id": "<guild_id>",
  "channel_id": "<channel_id>",
  "user_id": "<user_id>",
  "user_name": "<username>",
  "content": "<clean text>",
  "raw_content": "<original content with mentions>"
}
"""

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Pattern that matches QQ's mention tokens like <@!123456789>
_MENTION_RE = re.compile(r"<@!?\d+>")


def _parse_timestamp(ts_str: str) -> int:
    """Parse an ISO-8601 timestamp string and return a UTC Unix timestamp (int)."""
    try:
        # Python 3.11+ supports fromisoformat with timezone offsets directly;
        # for older versions we fall back to a manual strip.
        dt = datetime.fromisoformat(ts_str)
        return int(dt.astimezone(timezone.utc).timestamp())
    except Exception:
        logger.warning("Could not parse timestamp %r, using current time", ts_str)
        return int(datetime.now(timezone.utc).timestamp())


class MessageConverter:
    """Stateless converter between QQ and MaiBot message formats."""

    @staticmethod
    def qq_event_to_maibot(event_data: dict) -> dict:
        """Convert a QQ MESSAGE_CREATE / AT_MESSAGE_CREATE payload to MaiBot format."""
        author = event_data.get("author") or {}
        raw_content: str = event_data.get("content", "")
        # Strip mention tokens from the content so MaiBot sees clean text.
        clean_content = _MENTION_RE.sub("", raw_content).strip()

        return {
            "message_id": event_data.get("id", ""),
            "time": _parse_timestamp(event_data.get("timestamp", "")),
            "message_type": "guild",
            "guild_id": event_data.get("guild_id", ""),
            "channel_id": event_data.get("channel_id", ""),
            "user_id": author.get("id", ""),
            "user_name": author.get("username", ""),
            "content": clean_content,
            "raw_content": raw_content,
        }

    @staticmethod
    def maibot_to_qq_reply(maibot_response: dict) -> dict:
        """Convert a MaiBot response payload to the fields needed to send a QQ message."""
        return {
            "content": maibot_response.get("content", ""),
            "msg_id": maibot_response.get("message_id"),
            "channel_id": maibot_response.get("channel_id", ""),
        }
