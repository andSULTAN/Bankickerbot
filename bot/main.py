"""Bot entrypoint: long polling (webhook is optional, see README)."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import routers
from bot.runtime import Runtime
from core import strings
from core.config import get_scoring_config, get_settings
from core.db.session import Database
from core.logging import get_logger, setup_logging
from core.nsfw import get_classifier

log = get_logger(__name__)

REQUIRED_RIGHTS = ("can_delete_messages", "can_restrict_members")


async def verify_rights(runtime: Runtime) -> list[str]:
    """Check that the bot is an admin with delete/ban rights in every chat."""
    problems: list[str] = []
    me = await runtime.bot.get_me()
    for chat_id in runtime.protected_chat_ids:
        try:
            member = await runtime.bot.get_chat_member(chat_id, me.id)
        except Exception as exc:
            problems.append(f"{chat_id}: {exc}")
            continue
        if member.status != "administrator":
            problems.append(f"{chat_id}: admin emas (status={member.status})")
            continue
        missing = [right for right in REQUIRED_RIGHTS if not getattr(member, right, False)]
        if missing:
            problems.append(f"{chat_id}: {', '.join(missing)} yo'q")
    for problem in problems:
        log.error("rights_problem", detail=problem)
    return problems


async def notify_admins(runtime: Runtime, text: str) -> None:
    for admin_id in runtime.settings.admin_ids:
        try:
            await runtime.bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as exc:
            log.warning("admin_notify_failed", admin_id=admin_id, error=str(exc))


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN .env faylda to'ldirilmagan")

    cfg = get_scoring_config()
    db = Database(settings.database_url)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    runtime = Runtime(
        settings=settings,
        cfg=cfg,
        db=db,
        bot=bot,
        classifier=get_classifier(cfg.nsfw),
    )
    await runtime.load_mode()

    dispatcher = Dispatcher()
    dispatcher["runtime"] = runtime
    for router in routers:
        dispatcher.include_router(router)

    problems = await verify_rights(runtime)
    for problem in problems:
        await notify_admins(
            runtime, strings.RIGHTS_WARNING.format(chat=problem.split(":")[0], detail=problem)
        )

    log.info(
        "bot_started",
        mode=runtime.mode,
        channel=settings.channel_id,
        group=settings.discussion_group_id,
        review=settings.review_channel_id,
        admins=len(settings.admin_ids),
    )
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        await bot.session.close()
        await db.dispose()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        log.info("bot_stopped")


if __name__ == "__main__":
    main()
