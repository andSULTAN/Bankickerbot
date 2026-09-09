"""End-to-end check pipeline with a fake Bot API (no network)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiogram.types import User as TgUser

from bot.checks import check_user
from bot.runtime import Runtime
from core.config import Settings
from core.db.repo import Repository
from core.enums import DecisionSource, Verdict
from core.nsfw import StubClassifier

pytestmark = pytest.mark.asyncio

CHANNEL_ID = -1001111111111
GROUP_ID = -1002222222222
REVIEW_ID = -1003333333333


class FakeBot:
    """Only the handful of Bot API calls the pipeline actually uses."""

    def __init__(self, *, bio: str = "", with_photo: bool = True) -> None:
        self.bio = bio
        self.with_photo = with_photo
        self.sent: list[dict] = []
        self.banned: list[tuple[int, int]] = []
        self.unbanned: list[tuple[int, int]] = []
        self.deleted: list[tuple[int, int]] = []

    async def get_chat(self, user_id):
        return SimpleNamespace(bio=self.bio)

    async def get_user_profile_photos(self, user_id, limit=1):
        if not self.with_photo:
            return SimpleNamespace(photos=[])
        size = SimpleNamespace(file_id="file-1", file_unique_id="unique-1")
        return SimpleNamespace(photos=[[size]])

    async def download(self, file_id, destination):
        Path(destination).write_bytes(b"not-a-real-jpeg")

    async def send_photo(self, chat_id, photo, caption=None, **kwargs):
        self.sent.append({"chat_id": chat_id, "caption": caption, "photo": True, **kwargs})
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=len(self.sent))

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "caption": text, "photo": False, **kwargs})
        return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=len(self.sent))

    async def ban_chat_member(self, chat_id, user_id):
        self.banned.append((chat_id, user_id))

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=True):
        self.unbanned.append((chat_id, user_id))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


def make_settings(mode: str) -> Settings:
    return Settings(
        bot_token="test",
        database_url="sqlite+aiosqlite:///:memory:",
        admin_ids=[42],
        review_channel_id=REVIEW_ID,
        channel_id=CHANNEL_ID,
        discussion_group_id=GROUP_ID,
        mode=mode,
    )


@pytest_asyncio.fixture
async def runtime_factory(db, cfg):
    def build(mode: str = "enforce", *, nsfw: float = 0.97, bio: str = "", photo: bool = True):
        bot = FakeBot(bio=bio, with_photo=photo)
        runtime = Runtime(
            settings=make_settings(mode),
            cfg=cfg,
            db=db,
            bot=bot,
            classifier=StubClassifier(default=nsfw),
        )
        return runtime, bot

    return build


def tg_user(user_id: int = 5_900_000_777) -> TgUser:
    return TgUser(id=user_id, is_bot=False, first_name="Alina", username=None)


async def test_high_score_join_is_banned_in_enforce(runtime_factory, db):
    runtime, bot = runtime_factory("enforce", nsfw=0.97, bio="Yopiq kanal t.me/x")
    user = tg_user()

    plan = await check_user(runtime, user, chat_id=GROUP_ID)

    assert plan.ban
    assert sorted(chat for chat, _ in bot.banned) == sorted([CHANNEL_ID, GROUP_ID])
    # The auto-ban notice goes to the review channel, without decision buttons.
    assert bot.sent and bot.sent[0]["chat_id"] == REVIEW_ID
    assert bot.sent[0].get("reply_markup") is None

    async with db.session() as session:
        repo = Repository(session)
        assert await repo.is_blacklisted(user.id)
        assert await repo.spam_user_ids() == [user.id]
        assert (await repo.latest_check(user.id)).verdict == "ban"


async def test_observe_mode_never_bans(runtime_factory, db):
    runtime, bot = runtime_factory("observe", nsfw=0.97, bio="Yopiq kanal t.me/x")
    user = tg_user()

    plan = await check_user(runtime, user, chat_id=GROUP_ID)

    assert not plan.ban and plan.withheld_by_observe
    assert bot.banned == []
    assert bot.sent and bot.sent[0]["chat_id"] == REVIEW_ID
    # Buttons are attached so the profile can still be classified by hand.
    assert bot.sent[0].get("reply_markup") is not None

    async with db.session() as session:
        assert not await Repository(session).is_blacklisted(user.id)


async def test_whitelisted_user_is_untouched(runtime_factory, db):
    runtime, bot = runtime_factory("enforce", nsfw=0.99)
    user = tg_user()
    async with db.session() as session:
        repo = Repository(session)
        await repo.record_decision(
            user.id, Verdict.REAL, source=DecisionSource.MANUAL, decided_by=42
        )

    plan = await check_user(runtime, user, chat_id=GROUP_ID)

    assert not plan.acts
    assert bot.banned == [] and bot.sent == []


async def test_blacklisted_user_is_banned_again(runtime_factory, db):
    runtime, bot = runtime_factory("enforce", nsfw=0.0, photo=False)
    user = tg_user()
    async with db.session() as session:
        repo = Repository(session)
        await repo.record_decision(user.id, Verdict.SPAM, source=DecisionSource.MANUAL)

    plan = await check_user(runtime, user, chat_id=GROUP_ID)

    assert plan.ban and plan.source == "blacklist"
    assert sorted(chat for chat, _ in bot.banned) == sorted([CHANNEL_ID, GROUP_ID])


async def test_clean_user_is_left_alone(runtime_factory, db):
    runtime, bot = runtime_factory("enforce", nsfw=0.01, bio="Toshkentlik dasturchi")
    user = TgUser(id=1_200_000_888, is_bot=False, first_name="Jasur", username="jasur")

    plan = await check_user(runtime, user, chat_id=GROUP_ID)

    assert not plan.acts
    assert bot.banned == [] and bot.sent == []


async def test_admin_is_never_checked(runtime_factory):
    runtime, bot = runtime_factory("enforce", nsfw=0.99)
    plan = await check_user(runtime, TgUser(id=42, is_bot=False, first_name="Admin"),
                            chat_id=GROUP_ID)
    assert not plan.acts
    assert bot.sent == []


async def test_temp_photos_are_not_left_on_disk(runtime_factory, tmp_path):
    """Privacy: nothing downloaded may survive the check."""
    runtime, bot = runtime_factory("enforce", nsfw=0.01, bio="")
    await check_user(runtime, tg_user(), chat_id=GROUP_ID)
    leftovers = list(Path(tempdir_root()).glob("tgguard_bot_*"))
    assert leftovers == []


def tempdir_root() -> str:
    import tempfile

    return tempfile.gettempdir()


# --- private-chat testing tools ---------------------------------------------


def test_photo_report_flags_an_explicit_image(cfg):
    from bot.handlers.testing import format_photo_report

    runtime = SimpleNamespace(cfg=cfg)
    text = format_photo_report(
        0.97, [("FEMALE_BREAST_EXPOSED", 0.97), ("BUTTOCKS_EXPOSED", 0.61)], runtime
    )

    assert "0.97" in text
    assert "spam" in text  # verdict badge
    assert "FEMALE_BREAST_EXPOSED" in text
    assert "BUTTOCKS_EXPOSED" in text


def test_photo_report_on_a_clean_image(cfg):
    from bot.handlers.testing import format_photo_report
    from core import strings

    runtime = SimpleNamespace(cfg=cfg)
    text = format_photo_report(0.0, [], runtime)

    assert strings.PHOTO_TEST_NO_DETECTION.strip() in text
    assert "toza" in text


def test_photo_report_escapes_detection_labels(cfg):
    from bot.handlers.testing import format_photo_report

    runtime = SimpleNamespace(cfg=cfg)
    text = format_photo_report(0.5, [("<b>evil</b>", 0.5)], runtime)
    assert "<b>evil</b>" not in text
    assert "&lt;b&gt;evil&lt;/b&gt;" in text


def test_scan_summary_message():
    from scanner.cli import build_scan_summary
    from scanner.service import ScanStats

    flagged = build_scan_summary(
        ScanStats(seen=100, analyzed=90, cached=10, spam=3, review=7, clean=80),
        title="Kanal & Co",
        seconds=90,
    )
    assert "<b>3</b>" in flagged and "<b>7</b>" in flagged
    assert "tgguard apply" in flagged
    assert "Kanal &amp; Co" in flagged  # HTML-escaped title
    assert "1 daq 30 son" in flagged

    clean = build_scan_summary(ScanStats(seen=50, analyzed=50, clean=50), title="X", seconds=5)
    assert "topilmadi" in clean

    capped = build_scan_summary(
        ScanStats(seen=10000, analyzed=10000, clean=10000, capped=True), title="X", seconds=5
    )
    assert "10 000 dan katta" in capped
