"""Chat id conversions between the two Telegram id formats.

MTProto (Telethon) identifies a channel as a bare positive id (`1234567890`),
while the Bot API - and therefore `.env`, every bot update and everything a
user can copy out of a Telegram client - uses `-1001234567890`.

The database always stores the Bot API form, so a row written by the scanner
and a row written by the bot describe the same chat.
"""

from __future__ import annotations

# -1000000000000 - <channel id> == the Bot API form of that channel.
BOT_API_CHANNEL_BASE = -1_000_000_000_000


def to_bot_api_id(entity_id: int) -> int:
    """Telethon channel id -> Bot API id. Already-negative ids pass through."""
    if entity_id < 0:
        return entity_id
    return BOT_API_CHANNEL_BASE - entity_id


def to_telethon_id(chat_id: int) -> int:
    """Bot API id -> Telethon channel id. Positive ids pass through."""
    if chat_id >= 0:
        return chat_id
    if chat_id <= BOT_API_CHANNEL_BASE:
        return BOT_API_CHANNEL_BASE - chat_id
    # Legacy basic group: -123456789 -> 123456789
    return -chat_id
