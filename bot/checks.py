"""The real-time check pipeline used by the message and join handlers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from aiogram.types import Message
from aiogram.types import User as TgUser

from bot.moderation import ban_everywhere, delete_message
from bot.runtime import Runtime
from core import strings
from core.db.repo import Repository
from core.enums import Performer, ScoreVerdict
from core.logging import get_logger
from core.policy import Plan, decide
from core.review import publish_review
from core.scoring import CommentContext, ScoreResult, UserProfile, score_user

log = get_logger(__name__)


# --- profile fetching (Bot API) --------------------------------------------


async def fetch_bio(runtime: Runtime, user_id: int) -> str:
    """`getChat` exposes the bio, but only for users Telegram lets us see."""
    try:
        chat = await runtime.bot.get_chat(user_id)
    except Exception as exc:
        log.debug("bio_unavailable", user_id=user_id, error=str(exc))
        return ""
    return getattr(chat, "bio", "") or ""


async def fetch_photos(
    runtime: Runtime, user_id: int, workdir: Path
) -> tuple[str | None, list[Path]]:
    """Download up to `max_photos` profile photos; returns (photo identity, paths)."""
    try:
        photos = await runtime.bot.get_user_profile_photos(
            user_id, limit=runtime.cfg.nsfw.max_photos
        )
    except Exception as exc:
        log.debug("photos_unavailable", user_id=user_id, error=str(exc))
        return None, []
    if not photos or not photos.photos:
        return None, []

    identity: str | None = None
    paths: list[Path] = []
    for index, sizes in enumerate(photos.photos):
        if not sizes:
            continue
        largest = sizes[-1]
        if identity is None:
            identity = largest.file_unique_id
        target = workdir / f"{user_id}_{index}.jpg"
        try:
            await runtime.bot.download(largest.file_id, destination=str(target))
            paths.append(target)
        except Exception as exc:
            log.warning("photo_download_failed", user_id=user_id, error=str(exc))
    return identity, paths


async def build_profile(
    runtime: Runtime, user: TgUser, workdir: Path
) -> tuple[UserProfile, float, Path | None]:
    """Fresh profile snapshot + NSFW score + the photo kept for review."""
    bio = await fetch_bio(runtime, user.id)
    identity, paths = await fetch_photos(runtime, user.id, workdir)

    profile = UserProfile(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        bio=bio,
        has_photo=bool(paths),
        photo_id=identity,
        is_premium=bool(getattr(user, "is_premium", False)),
    )

    nsfw = 0.0
    if paths:
        nsfw = runtime.classifier.score_images([str(p) for p in paths])

    keep = paths[0] if paths else None
    for path in paths[1:]:
        path.unlink(missing_ok=True)
    return profile, nsfw, keep


def profile_from_row(user_row, tg_user: TgUser) -> UserProfile:
    """Cached snapshot (no downloads), refreshed with what the update gave us."""
    return UserProfile(
        telegram_id=user_row.telegram_id,
        username=tg_user.username or user_row.username,
        first_name=tg_user.first_name or user_row.first_name,
        last_name=tg_user.last_name or user_row.last_name,
        bio=user_row.bio or "",
        has_photo=user_row.has_photo,
        photo_id=user_row.photo_id,
        is_premium=bool(getattr(tg_user, "is_premium", user_row.is_premium)),
    )


def cached_nsfw(check) -> float:
    """Read the nsfw_photo signal value back out of a stored check."""
    if check is None:
        return 0.0
    for signal in (check.reasons or {}).get("signals", []):
        if signal.get("name") == "nsfw_photo":
            return float(signal.get("value", 0.0))
    return 0.0


def seconds_after_post(message: Message) -> float | None:
    """How long after the channel post the comment was written."""
    parent = message.reply_to_message
    if parent is None or not getattr(parent, "is_automatic_forward", False):
        return None
    if not (message.date and parent.date):
        return None
    return (message.date - parent.date).total_seconds()


# --- the pipeline -----------------------------------------------------------


async def check_user(
    runtime: Runtime,
    tg_user: TgUser,
    *,
    chat_id: int,
    message: Message | None = None,
) -> Plan:
    """Check one user (comment author or joiner) and apply the policy."""
    if tg_user.is_bot or runtime.is_admin(tg_user.id):
        return Plan(source="whitelist", reason="admin/bot")

    comment_text = (message.text or message.caption or "") if message else ""
    workdir = Path(tempfile.mkdtemp(prefix="tgguard_bot_"))
    photo_path: Path | None = None

    try:
        async with runtime.db.session() as session:
            repo = Repository(session)

            if await repo.is_whitelisted(tg_user.id):
                return Plan(source="whitelist", reason="oq ro'yxatda")

            user_row = await repo.get_user(tg_user.id)

            if await repo.is_blacklisted(tg_user.id):
                profile = (
                    profile_from_row(user_row, tg_user)
                    if user_row is not None
                    else _profile_from_tg(tg_user)
                )
                plan = decide(
                    None,
                    runtime.cfg,
                    mode=runtime.mode,
                    blacklisted=True,
                    has_message=message is not None,
                )
                await _execute(
                    runtime,
                    repo,
                    plan,
                    profile=profile,
                    result=None,
                    message=message,
                    chat_id=chat_id,
                    title=strings.REVIEW_TITLE_BLACKLIST,
                    comment_text=comment_text,
                    photo_path=None,
                    check_id=None,
                )
                return plan

            known_template = (
                await repo.is_known_template(comment_text) if comment_text else False
            )
            reuse_cache = False
            if user_row is not None:
                shallow = profile_from_row(user_row, tg_user)
                reuse_cache = not await repo.needs_recheck(
                    shallow, recheck_days=runtime.cfg.cache.recheck_days, channel_id=chat_id
                )

        # Network work happens outside the DB session.
        if reuse_cache and user_row is not None:
            profile = profile_from_row(user_row, tg_user)
            async with runtime.db.session() as session:
                nsfw = cached_nsfw(await Repository(session).latest_check(tg_user.id))
        else:
            profile, nsfw, photo_path = await build_profile(runtime, tg_user, workdir)

        comment = (
            CommentContext(
                text=comment_text,
                seconds_after_post=seconds_after_post(message) if message else None,
                known_template=known_template,
            )
            if comment_text
            else None
        )
        result: ScoreResult = score_user(
            profile,
            runtime.cfg,
            nsfw_score=nsfw if profile.has_photo else None,
            comment=comment,
        )

        async with runtime.db.session() as session:
            repo = Repository(session)
            await repo.upsert_user(profile, touch_checked=not reuse_cache)
            check = await repo.record_check(
                profile.telegram_id,
                result,
                source=Performer.BOT,
                channel_id=chat_id,
            )
            if comment_text:
                await repo.touch_comment_template(
                    comment_text, flagged=result.verdict != ScoreVerdict.IGNORE
                )

            plan = decide(
                result,
                runtime.cfg,
                mode=runtime.mode,
                has_message=message is not None,
            )
            title = _title_for(plan, result)
            already_pending = await repo.has_pending_review(profile.telegram_id)
            await _execute(
                runtime,
                repo,
                plan,
                profile=profile,
                result=result,
                message=message,
                chat_id=chat_id,
                title=title,
                comment_text=comment_text,
                photo_path=None if already_pending else photo_path,
                check_id=check.id,
                skip_review=already_pending,
            )
            if plan.review and not already_pending:
                photo_path = None  # publish_review already deleted it
        return plan

    finally:
        if photo_path is not None:
            Path(photo_path).unlink(missing_ok=True)
        try:
            for leftover in workdir.iterdir():
                leftover.unlink(missing_ok=True)
            workdir.rmdir()
        except OSError:
            pass


def _profile_from_tg(tg_user: TgUser) -> UserProfile:
    return UserProfile(
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name or "",
        last_name=tg_user.last_name or "",
        is_premium=bool(getattr(tg_user, "is_premium", False)),
    )


def _title_for(plan: Plan, result: ScoreResult) -> str:
    if plan.ban:
        return strings.REVIEW_TITLE_AUTOBAN
    if plan.withheld_by_observe:
        return strings.REVIEW_TITLE_OBSERVE
    return strings.REVIEW_TITLE_REVIEW


async def _execute(
    runtime: Runtime,
    repo: Repository,
    plan: Plan,
    *,
    profile: UserProfile,
    result: ScoreResult | None,
    message: Message | None,
    chat_id: int,
    title: str,
    comment_text: str,
    photo_path: Path | None,
    check_id: int | None,
    skip_review: bool = False,
) -> None:
    """Carry out the plan: delete, ban, and/or post to the review channel."""
    if plan.delete_message and message is not None:
        await delete_message(
            runtime.bot,
            repo,
            chat_id=message.chat.id,
            message_id=message.message_id,
            user_id=profile.telegram_id,
            reason=plan.reason,
        )

    if plan.ban:
        await ban_everywhere(
            runtime.bot,
            repo,
            user_id=profile.telegram_id,
            chat_ids=runtime.protected_chat_ids or [chat_id],
            reason=plan.reason,
        )
        await repo.close_pending_reviews_for_user(profile.telegram_id, state="auto_banned")

    if plan.review and not skip_review and runtime.settings.review_channel_id:
        extra = None
        if plan.ban:
            extra = f"↩️ Bekor qilish: <code>/unban {profile.telegram_id}</code>"
        elif plan.withheld_by_observe:
            extra = "ℹ️ observe rejimi: enforce bo'lganda ban qilinardi."
        await publish_review(
            runtime.bot,
            repo,
            review_chat_id=runtime.settings.review_channel_id,
            profile=profile,
            result=result,
            title=title,
            channel_id=chat_id,
            check_id=check_id,
            comment_text=comment_text or None,
            photo_path=photo_path,
            extra=extra,
            with_buttons=not plan.ban,
        )
