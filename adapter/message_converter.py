"""
message_converter.py – Convert messages between botpy format and maim_message format.

Incoming QQ messages (via botpy) are converted to the maim_message dict structure
expected by MaiBot.  MaiBot's reply segments are converted back to plain text (or
rich content) that can be sent through the botpy API.

Supported message types:
  - Guild @-mention  (botpy.message.Message)
  - Group @-mention  (botpy.message.GroupMessage)
  - C2C private      (botpy.message.C2CMessage)
  - Guild direct     (botpy.message.DirectMessage)

maim_message payload shape:
{
  "message_info": {
    "platform": "qq_official",
    "message_id": "<str>",
    "time": <float unix timestamp>,
    "group_info": {"group_id": "<str>", "group_name": "<str>"},
    "user_info":  {"user_id":  "<str>", "user_nickname": "<str>"},
    "additional_config": {
      "at_bot": true,
      "channel_id": "<str>",       // guild messages
      "message_type": "<str>",     // guild_at | group_at | c2c | direct
    }
  },
  "message_segment": {
    "type": "seglist",
    "data": [
      {"type": "text",  "data": "<str>"},
      {"type": "image", "data": "<url or base64>"},
      ...
    ]
  },
  "raw_message": "<original content string>"
}
"""

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Matches QQ mention tokens such as <@!123456789> or <@123456789>
_MENTION_RE = re.compile(r"<@!?\d+>")

# File extension sets used to classify attachments by type.
_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
_AUDIO_EXTS = frozenset({".mp3", ".wav", ".silk", ".amr"})
_VIDEO_EXTS = frozenset({".mp4", ".mov", ".avi"})


def _parse_timestamp(ts_str: str) -> float:
    """Parse an ISO-8601 timestamp and return a UTC Unix timestamp (float)."""
    if not ts_str:
        return _now()
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.astimezone(timezone.utc).timestamp()
    except (ValueError, OverflowError):
        logger.warning("Could not parse timestamp %r, using current time.", ts_str)
        return _now()


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _strip_mentions(content: str) -> str:
    """Remove mention tokens from *content* so MaiBot sees clean text."""
    return _MENTION_RE.sub("", content).strip()


def _content_to_segments(content: str, attachments: list | None = None) -> list:
    """
    Convert a message's text content and attachments into a seglist data array.

    Returns a list of segment dicts, e.g.:
      [{"type": "text", "data": "hello"}, {"type": "image", "data": "<url>"}]
    """
    segments: list = []
    clean = _strip_mentions(content or "")
    if clean:
        segments.append({"type": "text", "data": clean})

    for att in attachments or []:
        url = getattr(att, "url", None)
        content_type = getattr(att, "content_type", "") or ""
        if url:
            ext = "." + url.rsplit(".", 1)[-1].lower() if "." in url else ""
            if content_type.startswith("image/") or ext in _IMAGE_EXTS:
                segments.append({"type": "image", "data": url})
            elif content_type.startswith("audio/") or ext in _AUDIO_EXTS:
                segments.append({"type": "voice", "data": url})
            elif content_type.startswith("video/") or ext in _VIDEO_EXTS:
                segments.append({"type": "video", "data": url})
            else:
                segments.append({"type": "file", "data": url})

    return segments or [{"type": "text", "data": ""}]


class MessageConverter:
    """Stateless converter between botpy message objects and maim_message dicts."""

    # ------------------------------------------------------------------
    # QQ → maim_message
    # ------------------------------------------------------------------

    @staticmethod
    def guild_message_to_maibot(message) -> dict:
        """Convert a guild @-mention Message to maim_message format."""
        author = message.author
        return {
            "message_info": {
                "platform": "qq_official",
                "message_id": message.id,
                "time": _parse_timestamp(message.timestamp),
                "group_info": {
                    "group_id": message.guild_id,
                    "group_name": message.guild_id,
                },
                "user_info": {
                    "user_id": author.id,
                    "user_nickname": author.username,
                    "user_cardname": getattr(author, "username", ""),
                },
                "additional_config": {
                    "at_bot": True,
                    "channel_id": message.channel_id,
                    "message_type": "guild_at",
                },
            },
            "message_segment": {
                "type": "seglist",
                "data": _content_to_segments(
                    message.content, getattr(message, "attachments", None)
                ),
            },
            "raw_message": message.content,
        }

    @staticmethod
    def group_message_to_maibot(message) -> dict:
        """Convert a group @-mention GroupMessage to maim_message format."""
        author = message.author
        return {
            "message_info": {
                "platform": "qq_official",
                "message_id": message.id,
                "time": _parse_timestamp(message.timestamp),
                "group_info": {
                    "group_id": message.group_openid,
                    "group_name": message.group_openid,
                },
                "user_info": {
                    "user_id": author.member_openid,
                    "user_nickname": author.member_openid,
                    "user_cardname": "",
                },
                "additional_config": {
                    "at_bot": True,
                    "message_type": "group_at",
                },
            },
            "message_segment": {
                "type": "seglist",
                "data": _content_to_segments(
                    message.content, getattr(message, "attachments", None)
                ),
            },
            "raw_message": message.content,
        }

    @staticmethod
    def c2c_message_to_maibot(message) -> dict:
        """Convert a C2C (private) message to maim_message format."""
        author = message.author
        user_openid = author.user_openid
        return {
            "message_info": {
                "platform": "qq_official",
                "message_id": message.id,
                "time": _parse_timestamp(message.timestamp),
                # For C2C there is no group; we store user_openid as group_id
                # so MaiBot can route replies back to this specific user.
                "group_info": {
                    "group_id": user_openid,
                    "group_name": user_openid,
                },
                "user_info": {
                    "user_id": user_openid,
                    "user_nickname": user_openid,
                    "user_cardname": "",
                },
                "additional_config": {
                    "at_bot": True,
                    "message_type": "c2c",
                },
            },
            "message_segment": {
                "type": "seglist",
                "data": _content_to_segments(
                    message.content, getattr(message, "attachments", None)
                ),
            },
            "raw_message": message.content,
        }

    @staticmethod
    def direct_message_to_maibot(message) -> dict:
        """Convert a guild direct message to maim_message format."""
        author = message.author
        return {
            "message_info": {
                "platform": "qq_official",
                "message_id": message.id,
                "time": _parse_timestamp(message.timestamp),
                "group_info": {
                    "group_id": message.guild_id,
                    "group_name": message.guild_id,
                },
                "user_info": {
                    "user_id": author.id,
                    "user_nickname": getattr(author, "username", author.id),
                    "user_cardname": "",
                },
                "additional_config": {
                    "at_bot": True,
                    "message_type": "direct",
                },
            },
            "message_segment": {
                "type": "seglist",
                "data": _content_to_segments(
                    message.content, getattr(message, "attachments", None)
                ),
            },
            "raw_message": message.content,
        }

    # ------------------------------------------------------------------
    # maim_message reply → QQ
    # ------------------------------------------------------------------

    @staticmethod
    def maibot_reply_to_text(segment: dict) -> str:
        """
        Extract plain text from a maim_message segment dict.

        Concatenates all ``text`` segments; non-text segments are described
        in brackets so the user is aware of them (e.g. ``[图片]``).
        """
        if not segment:
            return ""
        return _extract_text(segment)


def _extract_text(seg: dict) -> str:
    """Recursively extract text from a segment dict."""
    seg_type = seg.get("type", "")
    data = seg.get("data")

    if seg_type == "seglist":
        parts = [_extract_text(s) for s in (data or [])]
        return "".join(p for p in parts if p)
    elif seg_type == "text":
        return str(data) if data else ""
    elif seg_type == "image":
        return "[图片]"
    elif seg_type in ("imageurl", "emoji"):
        return "[图片]"
    elif seg_type == "voice":
        return "[语音]"
    elif seg_type == "video":
        return "[视频]"
    elif seg_type == "file":
        return "[文件]"
    elif seg_type == "face":
        return "[表情]"
    elif seg_type == "reply":
        return ""
    else:
        return str(data) if data else ""
