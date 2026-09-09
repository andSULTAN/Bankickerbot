"""Turning a Telethon `User` into a scored profile (bio + photos + NSFW)."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import User

from core.config import ScoringConfig
from core.logging import get_logger
from core.nsfw import NsfwClassifier
from core.scoring import ScoreResult, UserProfile, score_user
from scanner.client import flood_safe

log = get_logger(__name__)


@dataclass
class ScannedUser:
    profile: UserProfile
    result: ScoreResult
    nsfw_score: float
    # Kept only until the review message is sent; deleted right afterwards.
    photo_path: Path | None = None


def to_profile(user: User, bio: str = "") -> UserProfile:
    photo = getattr(user, "photo", None)
    return UserProfile(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        bio=bio,
        has_photo=photo is not None,
        photo_id=str(getattr(photo, "photo_id", "")) or None,
        is_premium=bool(getattr(user, "premium", False)),
    )


async def fetch_bio(client: TelegramClient, user: User) -> str:
    full = await flood_safe(
        lambda: client(GetFullUserRequest(user)),
        what=f"GetFullUser({user.id})",
        reraise=False,
        default=None,
    )
    if full is None:
        return ""
    return getattr(full.full_user, "about", "") or ""


async def download_photos(
    client: TelegramClient, user: User, *, limit: int, workdir: Path
) -> list[Path]:
    """Download up to `limit` recent profile photos into a temp folder."""
    photos = await flood_safe(
        lambda: client.get_profile_photos(user, limit=limit),
        what=f"get_profile_photos({user.id})",
        reraise=False,
        default=[],
    )
    paths: list[Path] = []
    for index, photo in enumerate(photos or []):
        target = workdir / f"{user.id}_{index}.jpg"
        saved = await flood_safe(
            lambda p=photo, t=target: client.download_media(p, file=str(t)),
            what=f"download_media({user.id})",
            reraise=False,
            default=None,
        )
        if saved:
            paths.append(Path(saved))
    return paths


async def analyze_user(
    client: TelegramClient,
    user: User,
    cfg: ScoringConfig,
    classifier: NsfwClassifier,
    *,
    workdir: Path | None = None,
    keep_photo: bool = True,
) -> ScannedUser:
    """Full analysis of one user: bio, photos, NSFW, score."""
    bio = await fetch_bio(client, user)
    profile = to_profile(user, bio)

    nsfw = 0.0
    photo_path: Path | None = None
    paths: list[Path] = []

    if profile.has_photo:
        if workdir is None:
            # Not a context manager on purpose: the kept photo must outlive this
            # call until the review message is sent (publish_review deletes it).
            workdir = Path(tempfile.mkdtemp(prefix="tgguard_"))
        paths = await download_photos(client, user, limit=cfg.nsfw.max_photos, workdir=workdir)
        if paths:
            nsfw = classifier.score_images([str(p) for p in paths])

    result = score_user(profile, cfg, nsfw_score=nsfw if profile.has_photo else None)

    # Keep the most recent photo only if we may have to show it for review.
    if paths:
        keep_index = 0 if keep_photo else -1
        for index, path in enumerate(paths):
            if index == keep_index:
                photo_path = path
                continue
            path.unlink(missing_ok=True)

    return ScannedUser(profile=profile, result=result, nsfw_score=nsfw, photo_path=photo_path)
