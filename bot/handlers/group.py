"""Real-time checks in the discussion group: new comments and new members."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import ChatMemberUpdated, Message

from bot.checks import check_user
from bot.runtime import Runtime
from core.logging import get_logger

log = get_logger(__name__)

router = Router(name="group")

JOINED_STATUSES = {"member", "restricted"}
LEFT_STATUSES = {"left", "kicked"}


def _is_protected(runtime: Runtime, chat_id: int) -> bool:
    return chat_id in runtime.protected_chat_ids


@router.message()
async def on_group_message(message: Message, runtime: Runtime) -> None:
    """Every new comment in the discussion group."""
    if message.chat.type not in {"group", "supergroup"}:
        return
    if not _is_protected(runtime, message.chat.id):
        return
    # The auto-forwarded channel post itself, or an anonymous/channel sender.
    if message.is_automatic_forward or message.from_user is None:
        return
    if message.from_user.is_bot:
        return

    plan = await check_user(
        runtime, message.from_user, chat_id=message.chat.id, message=message
    )
    if plan.acts:
        log.info(
            "comment_checked",
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            ban=plan.ban,
            review=plan.review,
            source=plan.source,
            reason=plan.reason,
        )


@router.chat_member()
async def on_chat_member(event: ChatMemberUpdated, runtime: Runtime) -> None:
    """Someone joined (or was added to) a protected chat."""
    if not _is_protected(runtime, event.chat.id):
        return
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    if new_status not in JOINED_STATUSES or old_status not in LEFT_STATUSES:
        return

    user = event.new_chat_member.user
    if user.is_bot:
        return

    plan = await check_user(runtime, user, chat_id=event.chat.id)
    log.info(
        "join_checked",
        user_id=user.id,
        chat_id=event.chat.id,
        ban=plan.ban,
        review=plan.review,
        source=plan.source,
    )
