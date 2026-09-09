"""Scanner orchestration: scan, report, apply, unban."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from aiogram import Bot
from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import User as TLUser

from core import strings
from core.config import ScoringConfig, Settings
from core.db.repo import Repository
from core.db.session import Database
from core.enums import (
    ActionStatus,
    ActionType,
    DecisionSource,
    Performer,
    ScoreVerdict,
    Verdict,
)
from core.logging import get_logger
from core.nsfw import NsfwClassifier
from core.review import publish_review
from core.scoring import UserProfile
from scanner.actions import ban_user, unban_user
from scanner.client import flood_safe
from scanner.enumeration import EnumerationReport, iter_participants
from scanner.profiles import analyze_user, to_profile

log = get_logger(__name__)


@dataclass
class ScanStats:
    seen: int = 0
    analyzed: int = 0
    cached: int = 0
    spam: int = 0
    review: int = 0
    clean: int = 0
    photoless: int = 0
    whitelisted: int = 0
    errors: int = 0
    capped: bool = False
    queries: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "seen": self.seen,
            "analyzed": self.analyzed,
            "cached": self.cached,
            "spam": self.spam,
            "review": self.review,
            "clean": self.clean,
            "photoless": self.photoless,
            "whitelisted": self.whitelisted,
            "errors": self.errors,
            "capped": self.capped,
        }


@dataclass
class Targets:
    channel: object
    channel_id: int
    channel_title: str
    group: object | None
    group_id: int | None
    channel_members: int = 0
    group_members: int = 0

    @property
    def expected_total(self) -> int:
        return (self.channel_members or 0) + (self.group_members or 0)


class ScannerService:
    def __init__(
        self,
        *,
        settings: Settings,
        cfg: ScoringConfig,
        db: Database,
        client: TelegramClient,
        classifier: NsfwClassifier,
        bot: Bot | None = None,
    ) -> None:
        self.settings = settings
        self.cfg = cfg
        self.db = db
        self.client = client
        self.classifier = classifier
        self.bot = bot

    # --- targets -----------------------------------------------------------

    async def resolve_targets(self, channel_ref: str | int) -> Targets:
        entity = await self.client.get_entity(channel_ref)
        full = await self.client(GetFullChannelRequest(entity))
        linked_id = getattr(full.full_chat, "linked_chat_id", None)
        group = None
        group_members = 0
        if linked_id:
            try:
                group = await self.client.get_entity(linked_id)
                group_full = await self.client(GetFullChannelRequest(group))
                group_members = getattr(group_full.full_chat, "participants_count", 0) or 0
            except Exception as exc:  # linked chat may be inaccessible
                log.warning("linked_group_unavailable", linked_id=linked_id, error=str(exc))
        return Targets(
            channel=entity,
            channel_id=entity.id,
            channel_title=getattr(entity, "title", str(entity.id)),
            group=group,
            group_id=getattr(group, "id", None),
            channel_members=getattr(full.full_chat, "participants_count", 0) or 0,
            group_members=group_members,
        )

    # --- scan --------------------------------------------------------------

    async def scan(
        self,
        channel_ref: str | int,
        *,
        limit: int | None = None,
        force: bool = False,
        push_review: bool = True,
        profile_delay: float = 0.35,
        progress_cb: Callable[[ScanStats, str], None] | None = None,
        on_start: Callable[[Targets], None] | None = None,
    ) -> ScanStats:
        targets = await self.resolve_targets(channel_ref)
        if on_start:
            on_start(targets)
        stats = ScanStats()
        workdir = Path(tempfile.mkdtemp(prefix="tgguard_scan_"))

        async with self.db.session() as session:
            repo = Repository(session)
            await repo.upsert_channel(
                targets.channel_id,
                title=targets.channel_title,
                username=getattr(targets.channel, "username", None),
                linked_group_id=targets.group_id,
                review_channel_id=self.settings.review_channel_id or None,
            )
            run = await repo.start_or_resume_run(targets.channel_id, targets.group_id)
            run_id = run.id
            cursor = dict(run.cursor or {})

        phases = [("channel", targets.channel), ("group", targets.group)]
        for phase, entity in phases:
            if entity is None:
                continue
            done = set(cursor.get(f"{phase}_queries", []))
            report = EnumerationReport()

            # Loop variables are bound as defaults: the callback is only ever
            # called during this iteration, but keep it explicit.
            def _query_done(query: str, count: int, phase=phase, done=done) -> None:
                done.add(query)
                cursor[f"{phase}_queries"] = sorted(done)
                cursor["phase"] = phase

            async for tl_user in iter_participants(
                self.client,
                entity,
                done_queries=done,
                on_query_done=_query_done,
                report=report,
            ):
                stats.seen += 1
                try:
                    await self._process_user(
                        tl_user,
                        run_id=run_id,
                        targets=targets,
                        stats=stats,
                        force=force,
                        push_review=push_review,
                        workdir=workdir,
                    )
                except Exception as exc:
                    stats.errors += 1
                    log.error("user_scan_failed", user_id=tl_user.id, error=str(exc))

                if progress_cb:
                    progress_cb(stats, phase)
                if stats.seen % 25 == 0:
                    await self._checkpoint(run_id, cursor, stats)
                if limit and stats.seen >= limit:
                    break
                if profile_delay:
                    await asyncio.sleep(profile_delay)

            stats.capped = stats.capped or report.capped
            stats.queries = report.queries_used
            await self._checkpoint(run_id, cursor, stats)
            if limit and stats.seen >= limit:
                break

        async with self.db.session() as session:
            repo = Repository(session)
            await repo.update_run(run_id, cursor=cursor, stats=stats.as_dict(), status="finished")
        return stats

    async def _checkpoint(self, run_id: int, cursor: dict, stats: ScanStats) -> None:
        async with self.db.session() as session:
            repo = Repository(session)
            await repo.update_run(run_id, cursor=cursor, stats=stats.as_dict())

    async def _process_user(
        self,
        tl_user: TLUser,
        *,
        run_id: int,
        targets: Targets,
        stats: ScanStats,
        force: bool,
        push_review: bool,
        workdir: Path,
    ) -> None:
        async with self.db.session() as session:
            repo = Repository(session)
            if await repo.is_seen(run_id, tl_user.id):
                return
            if await repo.is_whitelisted(tl_user.id):
                stats.whitelisted += 1
                await repo.mark_seen(run_id, tl_user.id)
                return

            shallow = to_profile(tl_user)
            if not force and not await repo.needs_recheck(
                shallow, recheck_days=self.cfg.cache.recheck_days, channel_id=targets.channel_id
            ):
                stats.cached += 1
                await repo.mark_seen(run_id, tl_user.id)
                return

        scanned = await analyze_user(
            self.client, tl_user, self.cfg, self.classifier, workdir=workdir
        )
        profile: UserProfile = scanned.profile

        async with self.db.session() as session:
            repo = Repository(session)
            await repo.upsert_user(profile, touch_checked=True)
            check = await repo.record_check(
                profile.telegram_id,
                scanned.result,
                source=Performer.SCANNER,
                channel_id=targets.channel_id,
            )
            stats.analyzed += 1
            if not profile.has_photo:
                stats.photoless += 1

            verdict = scanned.result.verdict
            already_pending = await repo.has_pending_review(profile.telegram_id)

            if verdict == ScoreVerdict.BAN:
                stats.spam += 1
                await repo.record_decision(
                    profile.telegram_id,
                    Verdict.SPAM,
                    source=DecisionSource.AUTO,
                    channel_id=targets.channel_id,
                    note=scanned.result.reasons_text,
                )
                title = strings.REVIEW_TITLE_SCANNER_SPAM
            elif verdict == ScoreVerdict.REVIEW:
                stats.review += 1
                title = strings.REVIEW_TITLE_REVIEW
            else:
                stats.clean += 1
                title = None

            should_push = (
                push_review
                and title is not None
                and not already_pending
                and self.bot is not None
                and self.settings.review_channel_id
            )
            if should_push:
                await publish_review(
                    self.bot,
                    repo,
                    review_chat_id=self.settings.review_channel_id,
                    profile=profile,
                    result=scanned.result,
                    title=title,
                    channel_id=targets.channel_id,
                    channel_title=targets.channel_title,
                    check_id=check.id,
                    photo_path=scanned.photo_path,
                )
                scanned.photo_path = None

            await repo.mark_seen(run_id, profile.telegram_id)

        # Nothing may stay on disk: drop the photo we did not send.
        if scanned.photo_path is not None:
            Path(scanned.photo_path).unlink(missing_ok=True)

    # --- report ------------------------------------------------------------

    async def report(self) -> dict:
        async with self.db.session() as session:
            repo = Repository(session)
            summary = await repo.summary()
            summary["top_reasons"] = await repo.top_reasons()
            return summary

    async def list_users(self, **filters) -> list[dict]:
        """Flagged users with their profile links (DB only, no Telegram calls)."""
        async with self.db.session() as session:
            return await Repository(session).list_checked_users(**filters)

    # --- apply -------------------------------------------------------------

    async def apply(
        self,
        channel_ref: str | int,
        *,
        execute: bool = False,
        progress_cb: Callable[[int, int, int], None] | None = None,
    ) -> dict:
        """Ban every user whose latest decision is `spam`, in channel + group."""
        targets = await self.resolve_targets(channel_ref)
        async with self.db.session() as session:
            repo = Repository(session)
            user_ids = await repo.spam_user_ids()

        total = len(user_ids)
        banned = 0
        failed = 0
        interval = self.cfg.actions.bans_interval_seconds

        for index, user_id in enumerate(user_ids, start=1):
            if not execute:
                async with self.db.session() as session:
                    repo = Repository(session)
                    await repo.record_action(
                        user_id,
                        ActionType.BAN,
                        performed_by=Performer.SCANNER,
                        status=ActionStatus.DRY_RUN,
                        channel_id=targets.channel_id,
                        reason="apply --dry-run",
                    )
                if progress_cb:
                    progress_cb(index, total, banned)
                continue

            error: str | None = None
            for chat, chat_id in (
                (targets.channel, targets.channel_id),
                (targets.group, targets.group_id),
            ):
                if chat is None:
                    continue
                try:
                    await ban_user(self.client, chat, user_id)
                except Exception as exc:
                    error = str(exc)
                    log.error("ban_failed", user_id=user_id, chat_id=chat_id, error=error)

            async with self.db.session() as session:
                repo = Repository(session)
                await repo.record_action(
                    user_id,
                    ActionType.BAN,
                    performed_by=Performer.SCANNER,
                    status=ActionStatus.FAILED if error else ActionStatus.OK,
                    channel_id=targets.channel_id,
                    reason="latest decision = spam",
                    error=error,
                )
            if error:
                failed += 1
            else:
                banned += 1
            if progress_cb:
                progress_cb(index, total, banned)
            await asyncio.sleep(interval)

        return {"total": total, "banned": banned, "failed": failed, "executed": execute}

    # --- unban -------------------------------------------------------------

    async def unban(self, channel_ref: str | int, user_id: int) -> dict:
        targets = await self.resolve_targets(channel_ref)
        error: str | None = None
        for chat in (targets.channel, targets.group):
            if chat is None:
                continue
            try:
                await unban_user(self.client, chat, user_id)
            except Exception as exc:
                error = str(exc)
                log.error("unban_failed", user_id=user_id, error=error)

        async with self.db.session() as session:
            repo = Repository(session)
            await repo.record_action(
                user_id,
                ActionType.UNBAN,
                performed_by=Performer.SCANNER,
                status=ActionStatus.FAILED if error else ActionStatus.OK,
                channel_id=targets.channel_id,
                reason="manual unban",
                error=error,
            )
            # An unban is also a statement that this user is real.
            await repo.record_decision(
                user_id,
                Verdict.REAL,
                source=DecisionSource.MANUAL,
                channel_id=targets.channel_id,
                note="tgguard unban",
            )
        return {"user_id": user_id, "ok": error is None, "error": error}

    async def whoami(self) -> str:
        me = await flood_safe(self.client.get_me, what="get_me")
        return f"{me.first_name or ''} (@{me.username}) id={me.id}"
