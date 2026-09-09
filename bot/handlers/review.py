"""Inline buttons in the review channel: Spam / Haqiqiy / O'tkazish."""

from __future__ import annotations

import html
from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.moderation import ban_everywhere, unban_everywhere
from bot.runtime import Runtime
from core import strings
from core.db.repo import Repository
from core.enums import DecisionSource, Verdict
from core.logging import get_logger
from core.review import CALLBACK_PREFIX

log = get_logger(__name__)

router = Router(name="review")


@router.callback_query(F.data.startswith(f"{CALLBACK_PREFIX}:"))
async def on_review_button(callback: CallbackQuery, runtime: Runtime) -> None:
    if not runtime.is_admin(callback.from_user.id):
        await callback.answer(strings.CB_NOT_ADMIN, show_alert=True)
        return

    try:
        _, verdict_name, raw_id = (callback.data or "").split(":", 2)
        item_id = int(raw_id)
    except ValueError:
        await callback.answer(strings.CB_ERROR.format(error="callback"), show_alert=True)
        return

    async with runtime.db.session() as session:
        repo = Repository(session)
        item = await repo.get_review_item(item_id)
        if item is None:
            await callback.answer(strings.CB_ERROR.format(error="topilmadi"), show_alert=True)
            return
        if item.state != "pending":
            await callback.answer(strings.CB_ALREADY_DECIDED, show_alert=True)
            return

        user_id = item.user_id
        notice = strings.CB_DONE_SKIP

        if verdict_name == "spam":
            ok, error = await ban_everywhere(
                runtime.bot,
                repo,
                user_id=user_id,
                chat_ids=runtime.protected_chat_ids,
                reason=f"manual review by {callback.from_user.id}",
                decided_by=callback.from_user.id,
                manual=True,
            )
            notice = strings.CB_DONE_SPAM if ok else strings.CB_ERROR.format(error=error)
            await repo.close_review_item(item_id, state="spam")
        elif verdict_name == "real":
            await unban_everywhere(
                runtime.bot,
                repo,
                user_id=user_id,
                chat_ids=runtime.protected_chat_ids,
                reason=f"manual whitelist by {callback.from_user.id}",
                decided_by=callback.from_user.id,
                whitelist=True,
            )
            notice = strings.CB_DONE_REAL
            await repo.close_review_item(item_id, state="real")
        else:
            verdict_name = "skip"
            await repo.record_decision(
                user_id,
                Verdict.SKIP,
                source=DecisionSource.MANUAL,
                decided_by=callback.from_user.id,
                note="review skip",
            )
            await repo.close_review_item(item_id, state="skip")

    who = html.escape(callback.from_user.full_name or str(callback.from_user.id))
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    suffix = strings.REVIEW_DECIDED.format(
        verdict=strings.VERDICT_LABEL.get(verdict_name, verdict_name), who=who, when=stamp
    )

    message = callback.message
    try:
        if message is not None and message.photo:
            await message.edit_caption(
                caption=(message.caption or "") + suffix, parse_mode="HTML", reply_markup=None
            )
        elif message is not None:
            await message.edit_text(
                (message.html_text or message.text or "") + suffix,
                parse_mode="HTML",
                reply_markup=None,
                disable_web_page_preview=True,
            )
    except Exception as exc:  # message may be too old to edit
        log.warning("review_edit_failed", item_id=item_id, error=str(exc))

    log.info(
        "review_decided",
        item_id=item_id,
        user_id=user_id,
        verdict=verdict_name,
        by=callback.from_user.id,
    )
    await callback.answer(notice)
