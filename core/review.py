"""Publishing profiles to the private review channel (shared by scanner + bot).

Both components post through the *bot token*, so every review message comes from
one place and the inline buttons always work.
"""

from __future__ import annotations

import html
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from core import strings
from core.db.repo import Repository
from core.logging import get_logger
from core.scoring import ScoreResult, UserProfile

log = get_logger(__name__)

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

CALLBACK_PREFIX = "rv"


def review_keyboard(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=strings.BTN_SPAM, callback_data=f"{CALLBACK_PREFIX}:spam:{item_id}"
                ),
                InlineKeyboardButton(
                    text=strings.BTN_REAL, callback_data=f"{CALLBACK_PREFIX}:real:{item_id}"
                ),
                InlineKeyboardButton(
                    text=strings.BTN_SKIP, callback_data=f"{CALLBACK_PREFIX}:skip:{item_id}"
                ),
            ]
        ]
    )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_caption(
    profile: UserProfile,
    result: ScoreResult | None,
    *,
    title: str,
    channel_title: str | None = None,
    comment_text: str | None = None,
    extra: str | None = None,
    limit: int = CAPTION_LIMIT,
) -> str:
    parts = [title, strings.profile_line(profile.display_name, profile.telegram_id,
                                         profile.username)]
    if not profile.has_photo:
        parts.append(strings.REVIEW_NO_PHOTO)
    if profile.bio:
        parts.append(f"📝 <i>{html.escape(_clip(profile.bio, 300))}</i>")
    if result is not None:
        parts.append(f"⚖️ Ball: <b>{result.score:.2f}</b> ({result.verdict.value})")
        parts.append(f"🔍 Sabab: <code>{html.escape(_clip(result.reasons_text, 300))}</code>")
    if channel_title:
        parts.append(f"📢 {html.escape(channel_title)}")
    if comment_text:
        parts.append(f"💬 <i>{html.escape(_clip(comment_text, 300))}</i>")
    if extra:
        parts.append(extra)
    return _clip("\n".join(parts), limit)


async def publish_review(
    bot: Bot,
    repo: Repository,
    *,
    review_chat_id: int,
    profile: UserProfile,
    result: ScoreResult | None,
    title: str,
    channel_id: int | None = None,
    channel_title: str | None = None,
    check_id: int | None = None,
    comment_text: str | None = None,
    photo_path: str | Path | None = None,
    extra: str | None = None,
    with_buttons: bool = True,
):
    """Create a review item, post it, and remember the message id.

    The temporary photo (if any) is deleted right after sending - we never keep
    downloaded profile pictures on disk.
    """
    item = await repo.create_review_item(
        profile.telegram_id,
        channel_id=channel_id,
        check_id=check_id,
        comment_text=comment_text,
    )
    keyboard = review_keyboard(item.id) if with_buttons else None

    photo = Path(photo_path) if photo_path else None
    caption = build_caption(
        profile,
        result,
        title=title,
        channel_title=channel_title,
        comment_text=comment_text,
        extra=extra,
        limit=CAPTION_LIMIT if photo else TEXT_LIMIT,
    )

    message = None
    try:
        if photo and photo.exists():
            message = await bot.send_photo(
                review_chat_id,
                FSInputFile(str(photo)),
                caption=caption,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            message = await bot.send_message(
                review_chat_id,
                caption,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
    except Exception as exc:
        log.error("review_publish_failed", user_id=profile.telegram_id, error=str(exc))
        raise
    finally:
        if photo and photo.exists():
            try:
                photo.unlink()
            except OSError:  # pragma: no cover - best effort cleanup
                log.warning("temp_photo_unlink_failed", path=str(photo))

    if message is not None:
        await repo.attach_review_message(
            item.id, chat_id=message.chat.id, message_id=message.message_id
        )
    return item
