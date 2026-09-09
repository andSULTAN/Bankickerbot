"""Ban / unban through the service account (MTProto)."""

from __future__ import annotations

from telethon import TelegramClient
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights

from scanner.client import flood_safe

# view_messages=True in ChatBannedRights means "may NOT view messages" => banned.
BAN_RIGHTS = ChatBannedRights(
    until_date=None,
    view_messages=True,
    send_messages=True,
    send_media=True,
    send_stickers=True,
    send_gifs=True,
    send_games=True,
    send_inline=True,
    embed_links=True,
)
UNBAN_RIGHTS = ChatBannedRights(until_date=None, view_messages=False)


async def ban_user(client: TelegramClient, chat, user_id: int) -> None:
    await flood_safe(
        lambda: client(EditBannedRequest(chat, user_id, BAN_RIGHTS)),
        what=f"ban({user_id})",
    )


async def unban_user(client: TelegramClient, chat, user_id: int) -> None:
    await flood_safe(
        lambda: client(EditBannedRequest(chat, user_id, UNBAN_RIGHTS)),
        what=f"unban({user_id})",
    )
