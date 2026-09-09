"""Destructive actions through the Bot API, always logged to `actions`."""

from __future__ import annotations

from aiogram import Bot

from core.db.repo import Repository
from core.enums import ActionStatus, ActionType, DecisionSource, Performer, Verdict
from core.logging import get_logger

log = get_logger(__name__)


async def delete_message(
    bot: Bot, repo: Repository, *, chat_id: int, message_id: int, user_id: int, reason: str
) -> bool:
    error: str | None = None
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as exc:
        error = str(exc)
        log.warning("delete_failed", chat_id=chat_id, message_id=message_id, error=error)
    await repo.record_action(
        user_id,
        ActionType.DELETE,
        performed_by=Performer.BOT,
        status=ActionStatus.FAILED if error else ActionStatus.OK,
        channel_id=chat_id,
        reason=reason,
        error=error,
    )
    return error is None


async def ban_everywhere(
    bot: Bot,
    repo: Repository,
    *,
    user_id: int,
    chat_ids: list[int],
    reason: str,
    decided_by: int | None = None,
    manual: bool = False,
) -> tuple[bool, str | None]:
    """Ban from every protected chat and record the decision + actions."""
    last_error: str | None = None
    for chat_id in chat_ids:
        error: str | None = None
        try:
            await bot.ban_chat_member(chat_id, user_id)
        except Exception as exc:
            error = last_error = str(exc)
            log.error("ban_failed", chat_id=chat_id, user_id=user_id, error=error)
        await repo.record_action(
            user_id,
            ActionType.BAN,
            performed_by=Performer.BOT,
            status=ActionStatus.FAILED if error else ActionStatus.OK,
            channel_id=chat_id,
            reason=reason,
            error=error,
        )
    await repo.record_decision(
        user_id,
        Verdict.SPAM,
        source=DecisionSource.MANUAL if manual else DecisionSource.AUTO,
        decided_by=decided_by,
        note=reason,
    )
    return last_error is None, last_error


async def unban_everywhere(
    bot: Bot,
    repo: Repository,
    *,
    user_id: int,
    chat_ids: list[int],
    reason: str,
    decided_by: int | None = None,
    whitelist: bool = True,
) -> tuple[bool, str | None]:
    last_error: str | None = None
    for chat_id in chat_ids:
        error: str | None = None
        try:
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        except Exception as exc:
            error = last_error = str(exc)
            log.error("unban_failed", chat_id=chat_id, user_id=user_id, error=error)
        await repo.record_action(
            user_id,
            ActionType.UNBAN,
            performed_by=Performer.BOT,
            status=ActionStatus.FAILED if error else ActionStatus.OK,
            channel_id=chat_id,
            reason=reason,
            error=error,
        )
    if whitelist:
        await repo.record_decision(
            user_id,
            Verdict.REAL,
            source=DecisionSource.MANUAL,
            decided_by=decided_by,
            note=reason,
        )
    return last_error is None, last_error
