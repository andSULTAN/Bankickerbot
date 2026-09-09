"""Private-chat testing tools: send a photo (or forward a message) to the bot
and see exactly what the engine would decide - without touching anybody.
"""

from __future__ import annotations

import asyncio
import html
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.checks import build_profile
from bot.runtime import Runtime
from core import strings
from core.logging import get_logger
from core.scoring import UserProfile, score_user
from core.scoring import classify as classify_score

log = get_logger(__name__)

router = Router(name="testing")
router.message.filter(F.chat.type == "private")

MAX_DETECTIONS = 6
IMAGE_MIME_PREFIX = "image/"


def _is_admin(message: Message, runtime: Runtime) -> bool:
    return bool(message.from_user and runtime.is_admin(message.from_user.id))


def format_photo_report(
    nsfw: float,
    detections: list[tuple[str, float]],
    runtime: Runtime,
    *,
    unreadable: bool = False,
) -> str:
    """The reply for a photo sent to the bot. Pure function - easy to test."""
    if unreadable:
        return strings.PHOTO_TEST_UNREADABLE

    cfg = runtime.cfg
    weight = cfg.weights.get("nsfw_photo", 0.0)
    photo_score = min(1.0, max(0.0, nsfw * weight))
    verdict = classify_score(photo_score, cfg).value

    if detections:
        lines = [
            f"• <code>{html.escape(label)}</code> — {score:.2f}"
            for label, score in detections[:MAX_DETECTIONS]
        ]
        detail = strings.PHOTO_TEST_DETECTIONS_TITLE + "\n".join(lines)
    else:
        detail = strings.PHOTO_TEST_NO_DETECTION

    return (
        strings.PHOTO_TEST_RESULT.format(
            nsfw=nsfw,
            photo_score=photo_score,
            verdict=strings.VERDICT_BADGE.get(verdict, verdict),
            ban=cfg.thresholds.ban,
            review=cfg.thresholds.review,
            detections=detail,
        )
        + strings.PHOTO_TEST_HINT
    )


async def _analyze_file(runtime: Runtime, file_id: str) -> tuple[float, list[tuple[str, float]]]:
    """Download one file and score it off the event loop."""
    workdir = Path(tempfile.mkdtemp(prefix="tgguard_test_"))
    target = workdir / "photo.jpg"
    try:
        await runtime.bot.download(file_id, destination=str(target))
        # The classifier is CPU-bound: never block the polling loop with it.
        return await asyncio.to_thread(runtime.classifier.score_image_details, target)
    finally:
        target.unlink(missing_ok=True)
        try:
            workdir.rmdir()
        except OSError:  # pragma: no cover - best effort cleanup
            pass


@router.message(F.photo)
async def on_photo(message: Message, runtime: Runtime) -> None:
    """An admin sends a photo -> report what the NSFW model sees in it."""
    if not _is_admin(message, runtime):
        return
    placeholder = await message.answer(strings.PHOTO_TEST_WAIT)
    try:
        nsfw, detections = await _analyze_file(runtime, message.photo[-1].file_id)
        text = format_photo_report(nsfw, detections, runtime)
    except Exception as exc:
        log.error("photo_test_failed", error=str(exc))
        text = strings.CB_ERROR.format(error=html.escape(str(exc)))
    await placeholder.edit_text(text, parse_mode="HTML")


@router.message(F.document)
async def on_document(message: Message, runtime: Runtime) -> None:
    """Same, for a photo sent as a file ("without compression")."""
    if not _is_admin(message, runtime):
        return
    document = message.document
    if not (document.mime_type or "").startswith(IMAGE_MIME_PREFIX):
        return
    placeholder = await message.answer(strings.PHOTO_TEST_WAIT)
    try:
        nsfw, detections = await _analyze_file(runtime, document.file_id)
        text = format_photo_report(nsfw, detections, runtime)
    except Exception as exc:
        log.error("document_test_failed", error=str(exc))
        text = strings.CB_ERROR.format(error=html.escape(str(exc)))
    await placeholder.edit_text(text, parse_mode="HTML")


async def _report_profile(runtime: Runtime, user) -> str:
    """Full profile check (photo + bio + name) that changes nothing."""
    workdir = Path(tempfile.mkdtemp(prefix="tgguard_probe_"))
    photo_path = None
    try:
        profile, nsfw, photo_path = await build_profile(runtime, user, workdir)
        result = score_user(profile, runtime.cfg, nsfw_score=nsfw if profile.has_photo else None)
        return (
            f"{strings.PROFILE_TEST_TITLE}\n"
            f"{strings.profile_line(profile.display_name, profile.telegram_id, profile.username)}\n"
            f"{'' if profile.has_photo else strings.REVIEW_NO_PHOTO + chr(10)}"
            f"⚖️ Ball: <b>{result.score:.2f}</b> → "
            f"{strings.VERDICT_BADGE.get(result.verdict.value, result.verdict.value)}\n"
            f"🔍 Sabab: <code>{html.escape(result.reasons_text)}</code>"
        )
    finally:
        if photo_path is not None:
            Path(photo_path).unlink(missing_ok=True)
        try:
            workdir.rmdir()
        except OSError:  # pragma: no cover - best effort cleanup
            pass


@router.message(Command("check"))
async def cmd_check(message: Message, command: CommandObject, runtime: Runtime) -> None:
    """`/check <id>` - test one user by id, without acting on them."""
    if not _is_admin(message, runtime):
        await message.answer(strings.NOT_ADMIN)
        return
    raw = (command.args or "").strip().split()
    if not raw or not raw[0].lstrip("-").isdigit():
        await message.answer(strings.USAGE_ID.format(command="/check"), parse_mode="HTML")
        return

    placeholder = await message.answer(strings.PROFILE_TEST_WAIT)
    try:
        chat = await runtime.bot.get_chat(int(raw[0]))
        user = UserProfile(
            telegram_id=chat.id,
            username=getattr(chat, "username", None),
            first_name=getattr(chat, "first_name", "") or "",
            last_name=getattr(chat, "last_name", "") or "",
        )
        text = await _report_profile(runtime, _as_tg_user(user))
    except Exception as exc:
        log.error("check_failed", error=str(exc))
        text = strings.CB_ERROR.format(error=html.escape(str(exc)))
    await placeholder.edit_text(text, parse_mode="HTML")


@router.message(F.forward_from)
async def on_forward(message: Message, runtime: Runtime) -> None:
    """Forward a spammer's message here to see how it would be scored."""
    if not _is_admin(message, runtime):
        return
    placeholder = await message.answer(strings.PROFILE_TEST_WAIT)
    try:
        text = await _report_profile(runtime, message.forward_from)
    except Exception as exc:
        log.error("forward_test_failed", error=str(exc))
        text = strings.CB_ERROR.format(error=html.escape(str(exc)))
    await placeholder.edit_text(text, parse_mode="HTML")


@router.message(F.forward_sender_name)
async def on_hidden_forward(message: Message, runtime: Runtime) -> None:
    """Forwarded from someone whose account is hidden by privacy settings."""
    if not _is_admin(message, runtime):
        return
    await message.answer(strings.PROFILE_TEST_NO_USER, parse_mode="HTML")


def _as_tg_user(profile: UserProfile):
    """Adapter so `/check <id>` can reuse the aiogram-shaped code path."""
    from aiogram.types import User as TgUser

    return TgUser(
        id=profile.telegram_id,
        is_bot=False,
        first_name=profile.first_name or "",
        last_name=profile.last_name or None,
        username=profile.username,
    )
