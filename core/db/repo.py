"""Repository: every DB query the scanner and the bot need, in one place."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import (
    Action,
    Channel,
    Check,
    CommentTemplate,
    Decision,
    ReviewItem,
    ScanRun,
    ScanSeen,
    User,
)
from core.enums import ActionStatus, ActionType, DecisionSource, Performer, Verdict
from core.scoring import ScoreResult, UserProfile
from core.text_utils import template_hash


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- users -------------------------------------------------------------

    async def get_user(self, telegram_id: int) -> User | None:
        return await self.session.get(User, telegram_id)

    async def upsert_user(self, profile: UserProfile, *, touch_checked: bool = False) -> User:
        user = await self.session.get(User, profile.telegram_id)
        if user is None:
            user = User(telegram_id=profile.telegram_id, first_seen=_utcnow())
            self.session.add(user)
        user.username = profile.username
        user.first_name = profile.first_name or ""
        user.last_name = profile.last_name or ""
        user.bio = profile.bio or ""
        user.has_photo = profile.has_photo
        user.photo_id = profile.photo_id
        user.is_premium = profile.is_premium
        if touch_checked:
            user.last_checked = _utcnow()
        await self.session.flush()
        return user

    async def needs_recheck(
        self, profile: UserProfile, *, recheck_days: int, channel_id: int | None = None
    ) -> bool:
        """False when a fresh check exists and the profile photo has not changed."""
        user = await self.session.get(User, profile.telegram_id)
        if user is None or user.last_checked is None:
            return True
        if user.photo_id != profile.photo_id:
            return True
        last_checked = user.last_checked
        if last_checked.tzinfo is None:
            last_checked = last_checked.replace(tzinfo=UTC)
        if _utcnow() - last_checked > timedelta(days=recheck_days):
            return True
        stmt = select(Check.id).where(Check.user_id == profile.telegram_id)
        if channel_id is not None:
            stmt = stmt.where(Check.channel_id == channel_id)
        return (await self.session.scalar(stmt.limit(1))) is None

    # --- checks ------------------------------------------------------------

    async def record_check(
        self,
        user_id: int,
        result: ScoreResult,
        *,
        source: Performer,
        channel_id: int | None = None,
    ) -> Check:
        check = Check(
            user_id=user_id,
            channel_id=channel_id,
            score=result.score,
            verdict=result.verdict.value,
            reasons=result.to_json(),
            model_version=result.version,
            source=source,
            checked_at=_utcnow(),
        )
        self.session.add(check)
        await self.session.flush()
        return check

    async def latest_check(self, user_id: int) -> Check | None:
        stmt = (
            select(Check)
            .where(Check.user_id == user_id)
            .order_by(Check.checked_at.desc(), Check.id.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    # --- decisions (white / blacklist) -------------------------------------

    async def latest_decision(self, user_id: int) -> Decision | None:
        """Latest decision that actually classifies the user (`skip` is neutral)."""
        stmt = (
            select(Decision)
            .where(Decision.user_id == user_id, Decision.verdict != Verdict.SKIP)
            .order_by(Decision.decided_at.desc(), Decision.id.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def record_decision(
        self,
        user_id: int,
        verdict: Verdict,
        *,
        source: DecisionSource,
        decided_by: int | None = None,
        channel_id: int | None = None,
        note: str | None = None,
    ) -> Decision:
        decision = Decision(
            user_id=user_id,
            channel_id=channel_id,
            verdict=verdict,
            source=source,
            decided_by=decided_by,
            note=note,
            decided_at=_utcnow(),
        )
        self.session.add(decision)
        await self.session.flush()
        return decision

    async def is_blacklisted(self, user_id: int) -> bool:
        decision = await self.latest_decision(user_id)
        return decision is not None and decision.verdict == Verdict.SPAM

    async def is_whitelisted(self, user_id: int) -> bool:
        decision = await self.latest_decision(user_id)
        return (
            decision is not None
            and decision.verdict == Verdict.REAL
            and decision.source == DecisionSource.MANUAL
        )

    async def spam_user_ids(self) -> list[int]:
        """Everyone whose latest classifying decision is `spam` (the ban list)."""
        subquery = (
            select(Decision.user_id, func.max(Decision.id).label("last_id"))
            .where(Decision.verdict != Verdict.SKIP)
            .group_by(Decision.user_id)
            .subquery()
        )
        stmt = (
            select(Decision.user_id)
            .join(subquery, Decision.id == subquery.c.last_id)
            .where(Decision.verdict == Verdict.SPAM)
        )
        return list(await self.session.scalars(stmt))

    # --- actions -----------------------------------------------------------

    async def record_action(
        self,
        user_id: int,
        action: ActionType,
        *,
        performed_by: Performer,
        status: ActionStatus,
        channel_id: int | None = None,
        reason: str | None = None,
        error: str | None = None,
    ) -> Action:
        row = Action(
            user_id=user_id,
            channel_id=channel_id,
            action=action,
            performed_by=performed_by,
            status=status,
            reason=reason,
            error=error,
            created_at=_utcnow(),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    # --- review queue ------------------------------------------------------

    async def create_review_item(
        self,
        user_id: int,
        *,
        channel_id: int | None,
        check_id: int | None,
        comment_text: str | None = None,
    ) -> ReviewItem:
        item = ReviewItem(
            user_id=user_id,
            channel_id=channel_id,
            check_id=check_id,
            comment_text=comment_text,
            state="pending",
            created_at=_utcnow(),
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def attach_review_message(
        self, item_id: int, *, chat_id: int, message_id: int
    ) -> None:
        item = await self.session.get(ReviewItem, item_id)
        if item is None:
            return
        item.review_chat_id = chat_id
        item.review_message_id = message_id
        await self.session.flush()

    async def get_review_item(self, item_id: int) -> ReviewItem | None:
        return await self.session.get(ReviewItem, item_id)

    async def has_pending_review(self, user_id: int) -> bool:
        stmt = select(ReviewItem.id).where(
            ReviewItem.user_id == user_id, ReviewItem.state == "pending"
        )
        return (await self.session.scalar(stmt.limit(1))) is not None

    async def close_review_item(self, item_id: int, *, state: str) -> None:
        await self.session.execute(
            update(ReviewItem)
            .where(ReviewItem.id == item_id)
            .values(state=state, decided_at=_utcnow())
        )

    async def close_pending_reviews_for_user(self, user_id: int, *, state: str) -> None:
        await self.session.execute(
            update(ReviewItem)
            .where(ReviewItem.user_id == user_id, ReviewItem.state == "pending")
            .values(state=state, decided_at=_utcnow())
        )

    async def count_pending_reviews(self) -> int:
        stmt = select(func.count()).select_from(ReviewItem).where(ReviewItem.state == "pending")
        return int(await self.session.scalar(stmt) or 0)

    # --- comment templates -------------------------------------------------

    async def touch_comment_template(self, text: str, *, flagged: bool) -> bool:
        """Register a comment; return True if this template was already flagged before."""
        digest = template_hash(text)
        if not digest or not text.strip():
            return False
        row = await self.session.get(CommentTemplate, digest)
        known = bool(row and row.flagged_count > 0)
        if row is None:
            row = CommentTemplate(hash=digest, sample=text[:500], times_seen=0, flagged_count=0)
            self.session.add(row)
        row.times_seen += 1
        row.last_seen = _utcnow()
        if flagged:
            row.flagged_count += 1
        await self.session.flush()
        return known

    async def is_known_template(self, text: str) -> bool:
        digest = template_hash(text)
        row = await self.session.get(CommentTemplate, digest)
        return bool(row and row.flagged_count > 0)

    # --- channels ----------------------------------------------------------

    async def upsert_channel(
        self,
        channel_id: int,
        *,
        title: str | None = None,
        username: str | None = None,
        linked_group_id: int | None = None,
        review_channel_id: int | None = None,
    ) -> Channel:
        channel = await self.session.scalar(
            select(Channel).where(Channel.channel_id == channel_id)
        )
        if channel is None:
            channel = Channel(channel_id=channel_id, settings={})
            self.session.add(channel)
        if title is not None:
            channel.title = title
        if username is not None:
            channel.username = username
        if linked_group_id is not None:
            channel.linked_group_id = linked_group_id
        if review_channel_id is not None:
            channel.review_channel_id = review_channel_id
        await self.session.flush()
        return channel

    # --- scan runs (resume) ------------------------------------------------

    async def start_or_resume_run(self, channel_id: int, group_id: int | None) -> ScanRun:
        stmt = (
            select(ScanRun)
            .where(ScanRun.channel_id == channel_id, ScanRun.status == "running")
            .order_by(ScanRun.id.desc())
            .limit(1)
        )
        run = await self.session.scalar(stmt)
        if run is not None:
            return run
        run = ScanRun(
            channel_id=channel_id,
            group_id=group_id,
            status="running",
            cursor={"done_queries": [], "phase": "channel"},
            stats={},
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def update_run(
        self,
        run_id: int,
        *,
        cursor: dict | None = None,
        stats: dict | None = None,
        status: str | None = None,
        error: str | None = None,
    ) -> None:
        values: dict = {"updated_at": _utcnow()}
        if cursor is not None:
            values["cursor"] = cursor
        if stats is not None:
            values["stats"] = stats
        if status is not None:
            values["status"] = status
            if status in {"finished", "failed"}:
                values["finished_at"] = _utcnow()
        if error is not None:
            values["error"] = error
        await self.session.execute(update(ScanRun).where(ScanRun.id == run_id).values(**values))

    async def mark_seen(self, run_id: int, user_id: int) -> None:
        exists = await self.session.get(ScanSeen, (run_id, user_id))
        if exists is None:
            self.session.add(ScanSeen(run_id=run_id, user_id=user_id))
            await self.session.flush()

    async def is_seen(self, run_id: int, user_id: int) -> bool:
        return (await self.session.get(ScanSeen, (run_id, user_id))) is not None

    async def seen_count(self, run_id: int) -> int:
        stmt = select(func.count()).select_from(ScanSeen).where(ScanSeen.run_id == run_id)
        return int(await self.session.scalar(stmt) or 0)

    # --- reporting ---------------------------------------------------------

    async def summary(self) -> dict:
        """Counters for `tgguard report` and `/stats`."""
        total_users = int(
            await self.session.scalar(select(func.count()).select_from(User)) or 0
        )
        photoless = int(
            await self.session.scalar(
                select(func.count()).select_from(User).where(User.has_photo.is_(False))
            )
            or 0
        )

        latest_check = (
            select(Check.user_id, func.max(Check.id).label("last_id"))
            .group_by(Check.user_id)
            .subquery()
        )
        verdict_rows = await self.session.execute(
            select(Check.verdict, func.count())
            .join(latest_check, Check.id == latest_check.c.last_id)
            .group_by(Check.verdict)
        )
        by_verdict = {row[0]: int(row[1]) for row in verdict_rows}

        latest_decision = (
            select(Decision.user_id, func.max(Decision.id).label("last_id"))
            .where(Decision.verdict != Verdict.SKIP)
            .group_by(Decision.user_id)
            .subquery()
        )
        decision_rows = await self.session.execute(
            select(Decision.verdict, func.count())
            .join(latest_decision, Decision.id == latest_decision.c.last_id)
            .group_by(Decision.verdict)
        )
        by_decision = {
            (row[0].value if hasattr(row[0], "value") else row[0]): int(row[1])
            for row in decision_rows
        }

        action_rows = await self.session.execute(
            select(Action.action, func.count()).group_by(Action.action)
        )
        by_action = {
            (row[0].value if hasattr(row[0], "value") else row[0]): int(row[1])
            for row in action_rows
        }

        return {
            "users": total_users,
            "photoless": photoless,
            "checks_by_verdict": by_verdict,
            "decisions": by_decision,
            "actions": by_action,
            "pending_reviews": await self.count_pending_reviews(),
        }

    async def top_reasons(self, limit: int = 10) -> list[tuple[str, int]]:
        """Most frequent signal names among the latest checks (computed in Python:
        JSON aggregation differs too much between Postgres and sqlite)."""
        latest_check = (
            select(Check.user_id, func.max(Check.id).label("last_id"))
            .group_by(Check.user_id)
            .subquery()
        )
        rows = await self.session.scalars(
            select(Check.reasons).join(latest_check, Check.id == latest_check.c.last_id)
        )
        counter: dict[str, int] = {}
        for payload in rows:
            for reason in (payload or {}).get("reasons", []):
                key = str(reason).split("=")[0].split(" ")[0]
                counter[key] = counter.get(key, 0) + 1
        return sorted(counter.items(), key=lambda item: item[1], reverse=True)[:limit]
