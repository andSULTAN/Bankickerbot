"""Shared runtime state for the bot (DB, config, classifier, observe/enforce)."""

from __future__ import annotations

from aiogram import Bot
from sqlalchemy import select

from core.config import Mode, ScoringConfig, Settings
from core.db.models import Channel
from core.db.session import Database
from core.logging import get_logger
from core.nsfw import NsfwClassifier

log = get_logger(__name__)


class Runtime:
    """Everything the handlers need, created once in `main`."""

    def __init__(
        self,
        *,
        settings: Settings,
        cfg: ScoringConfig,
        db: Database,
        bot: Bot,
        classifier: NsfwClassifier,
    ) -> None:
        self.settings = settings
        self.cfg = cfg
        self.db = db
        self.bot = bot
        self.classifier = classifier
        self._mode: Mode = settings.mode

    # --- mode --------------------------------------------------------------

    @property
    def mode(self) -> Mode:
        return self._mode

    async def load_mode(self) -> Mode:
        """Mode survives restarts: it is stored in `channels.settings`."""
        if not self.settings.channel_id:
            return self._mode
        async with self.db.session() as session:
            channel = await session.scalar(
                select(Channel).where(Channel.channel_id == self.settings.channel_id)
            )
            stored = (channel.settings or {}).get("mode") if channel else None
        if stored in ("observe", "enforce"):
            self._mode = stored  # type: ignore[assignment]
        return self._mode

    async def set_mode(self, mode: Mode) -> None:
        self._mode = mode
        if not self.settings.channel_id:
            return
        async with self.db.session() as session:
            channel = await session.scalar(
                select(Channel).where(Channel.channel_id == self.settings.channel_id)
            )
            if channel is None:
                channel = Channel(channel_id=self.settings.channel_id, settings={})
                session.add(channel)
            settings_json = dict(channel.settings or {})
            settings_json["mode"] = mode
            channel.settings = settings_json
        log.info("mode_changed", mode=mode)

    # --- helpers -----------------------------------------------------------

    @property
    def protected_chat_ids(self) -> list[int]:
        return [
            chat_id
            for chat_id in (self.settings.channel_id, self.settings.discussion_group_id)
            if chat_id
        ]

    def is_admin(self, user_id: int) -> bool:
        return self.settings.is_admin(user_id)
