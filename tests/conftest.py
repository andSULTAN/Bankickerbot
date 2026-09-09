"""Shared fixtures. No network, no model download, no Postgres."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The stub classifier must be selected before anything imports core.nsfw.
os.environ.setdefault("TGGUARD_NSFW_BACKEND", "stub")

from core.config import ScoringConfig
from core.db.session import Database
from core.scoring import UserProfile


@pytest.fixture(scope="session")
def cfg() -> ScoringConfig:
    return ScoringConfig.load(ROOT / "config" / "scoring.yaml")


@pytest_asyncio.fixture
async def db(tmp_path) -> Database:
    database = Database(f"sqlite+aiosqlite:///{tmp_path.as_posix()}/test.db")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


# --- profile fixtures -------------------------------------------------------


@pytest.fixture
def spam_profile() -> UserProfile:
    """Typical wave account: explicit photo + adult channel ad in the bio."""
    return UserProfile(
        telegram_id=5_900_000_001,
        username=None,
        first_name="Alina 🔞",
        last_name="",
        bio="Yopiq kanal 18+ kirish t.me/hotchannel",
        has_photo=True,
        photo_id="p-spam-1",
        is_premium=False,
    )


@pytest.fixture
def real_profile() -> UserProfile:
    return UserProfile(
        telegram_id=1_200_000_002,
        username="jasur_dev",
        first_name="Jasur",
        last_name="Karimov",
        bio="Backend dasturchi, Toshkent",
        has_photo=True,
        photo_id="p-real-1",
        is_premium=True,
    )


@pytest.fixture
def photoless_links_profile() -> UserProfile:
    return UserProfile(
        telegram_id=6_100_000_003,
        username=None,
        first_name="🔞 18+",
        last_name="t.me/private",
        bio="Yopiq kanal, ssылка в профиле, t.me/joinchat/xxx https://example.com",
        has_photo=False,
        photo_id=None,
    )


@pytest.fixture
def photoless_clean_profile() -> UserProfile:
    """No photo, no username, brand new id - must never be auto-banned."""
    return UserProfile(
        telegram_id=6_900_000_004,
        username=None,
        first_name="Dilnoza",
        last_name="",
        bio="",
        has_photo=False,
        photo_id=None,
    )
