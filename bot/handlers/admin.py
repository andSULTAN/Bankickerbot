"""Admin commands (private chat only)."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy import text

from bot.moderation import ban_everywhere, unban_everywhere
from bot.runtime import Runtime
from core import strings
from core.db.repo import Repository
from core.enums import DecisionSource, Verdict
from core.logging import get_logger

log = get_logger(__name__)

router = Router(name="admin")
# Everything in this router is private chat only.
router.message.filter(F.chat.type == "private")


def _deny(message: Message, runtime: Runtime) -> bool:
    return not runtime.is_admin(message.from_user.id if message.from_user else 0)


def _parse_id(command: CommandObject) -> int | None:
    if not command.args:
        return None
    try:
        return int(command.args.strip().split()[0])
    except ValueError:
        return None


@router.message(CommandStart())
async def cmd_start(message: Message, runtime: Runtime) -> None:
    if _deny(message, runtime):
        await message.answer(strings.NOT_ADMIN)
        return
    await message.answer(strings.START, parse_mode="HTML")


@router.message(Command("stats"))
async def cmd_stats(message: Message, runtime: Runtime) -> None:
    if _deny(message, runtime):
        await message.answer(strings.NOT_ADMIN)
        return
    async with runtime.db.session() as session:
        data = await Repository(session).summary()
    verdicts = data["checks_by_verdict"]
    decisions = data["decisions"]
    actions = ", ".join(f"{k}={v}" for k, v in sorted(data["actions"].items())) or "-"
    await message.answer(
        strings.STATS.format(
            users=data["users"],
            photoless=data["photoless"],
            ban=verdicts.get("ban", 0),
            review=verdicts.get("review", 0),
            ignore=verdicts.get("ignore", 0),
            spam=decisions.get("spam", 0),
            real=decisions.get("real", 0),
            pending=data["pending_reviews"],
            actions=actions,
            mode=runtime.mode,
        ),
        parse_mode="HTML",
    )


@router.message(Command("pending"))
async def cmd_pending(message: Message, runtime: Runtime) -> None:
    if _deny(message, runtime):
        await message.answer(strings.NOT_ADMIN)
        return
    async with runtime.db.session() as session:
        count = await Repository(session).count_pending_reviews()
    await message.answer(strings.PENDING.format(count=count), parse_mode="HTML")


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject, runtime: Runtime) -> None:
    if _deny(message, runtime):
        await message.answer(strings.NOT_ADMIN)
        return
    user_id = _parse_id(command)
    if user_id is None:
        await message.answer(strings.USAGE_ID.format(command="/ban"), parse_mode="HTML")
        return
    async with runtime.db.session() as session:
        repo = Repository(session)
        ok, error = await ban_everywhere(
            runtime.bot,
            repo,
            user_id=user_id,
            chat_ids=runtime.protected_chat_ids,
            reason=f"/ban by {message.from_user.id}",
            decided_by=message.from_user.id,
            manual=True,
        )
        await repo.close_pending_reviews_for_user(user_id, state="spam")
    await message.answer(
        strings.BANNED_OK.format(user_id=user_id)
        if ok
        else strings.BANNED_FAIL.format(error=error),
        parse_mode="HTML",
    )


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject, runtime: Runtime) -> None:
    if _deny(message, runtime):
        await message.answer(strings.NOT_ADMIN)
        return
    user_id = _parse_id(command)
    if user_id is None:
        await message.answer(strings.USAGE_ID.format(command="/unban"), parse_mode="HTML")
        return
    async with runtime.db.session() as session:
        repo = Repository(session)
        ok, error = await unban_everywhere(
            runtime.bot,
            repo,
            user_id=user_id,
            chat_ids=runtime.protected_chat_ids,
            reason=f"/unban by {message.from_user.id}",
            decided_by=message.from_user.id,
            whitelist=True,
        )
        await repo.close_pending_reviews_for_user(user_id, state="real")
    await message.answer(
        strings.UNBANNED_OK.format(user_id=user_id)
        if ok
        else strings.UNBANNED_FAIL.format(error=error),
        parse_mode="HTML",
    )


@router.message(Command("whitelist"))
async def cmd_whitelist(message: Message, command: CommandObject, runtime: Runtime) -> None:
    if _deny(message, runtime):
        await message.answer(strings.NOT_ADMIN)
        return
    user_id = _parse_id(command)
    if user_id is None:
        await message.answer(strings.USAGE_ID.format(command="/whitelist"), parse_mode="HTML")
        return
    async with runtime.db.session() as session:
        repo = Repository(session)
        await repo.record_decision(
            user_id,
            Verdict.REAL,
            source=DecisionSource.MANUAL,
            decided_by=message.from_user.id,
            note="/whitelist",
        )
        await repo.close_pending_reviews_for_user(user_id, state="real")
    await message.answer(strings.WHITELIST_OK.format(user_id=user_id), parse_mode="HTML")


@router.message(Command("mode"))
async def cmd_mode(message: Message, command: CommandObject, runtime: Runtime) -> None:
    if _deny(message, runtime):
        await message.answer(strings.NOT_ADMIN)
        return
    arg = (command.args or "").strip().lower()
    if not arg:
        await message.answer(strings.MODE_CURRENT.format(mode=runtime.mode), parse_mode="HTML")
        return
    if arg not in {"observe", "enforce"}:
        await message.answer(strings.MODE_INVALID)
        return
    await runtime.set_mode(arg)  # type: ignore[arg-type]
    await message.answer(strings.MODE_CHANGED.format(mode=arg), parse_mode="HTML")


@router.message(Command("health"))
async def cmd_health(message: Message, runtime: Runtime) -> None:
    if _deny(message, runtime):
        await message.answer(strings.NOT_ADMIN)
        return
    try:
        async with runtime.db.session() as session:
            await session.execute(text("SELECT 1"))
        db_state = "OK"
    except Exception as exc:
        db_state = f"XATO: {exc}"
    await message.answer(
        strings.HEALTH_OK.format(
            mode=runtime.mode,
            db=db_state,
            channel=runtime.settings.channel_id,
            group=runtime.settings.discussion_group_id,
            review=runtime.settings.review_channel_id,
        ),
        parse_mode="HTML",
    )
