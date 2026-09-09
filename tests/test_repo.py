"""Repository: decision precedence, review state machine, caching, templates."""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.db.repo import Repository
from core.enums import ActionStatus, ActionType, DecisionSource, Performer, Verdict
from core.scoring import score_user

pytestmark = pytest.mark.asyncio


async def test_blacklist_and_whitelist_precedence(db, spam_profile):
    async with db.session() as session:
        repo = Repository(session)
        await repo.upsert_user(spam_profile)

        assert not await repo.is_blacklisted(spam_profile.telegram_id)

        await repo.record_decision(
            spam_profile.telegram_id, Verdict.SPAM, source=DecisionSource.AUTO
        )
        assert await repo.is_blacklisted(spam_profile.telegram_id)
        assert not await repo.is_whitelisted(spam_profile.telegram_id)

        # A later manual "real" decision wins: the user becomes whitelisted.
        await repo.record_decision(
            spam_profile.telegram_id,
            Verdict.REAL,
            source=DecisionSource.MANUAL,
            decided_by=1,
        )
        assert await repo.is_whitelisted(spam_profile.telegram_id)
        assert not await repo.is_blacklisted(spam_profile.telegram_id)

        # `skip` is neutral: it must not undo the whitelist.
        await repo.record_decision(
            spam_profile.telegram_id, Verdict.SKIP, source=DecisionSource.MANUAL, decided_by=1
        )
        assert await repo.is_whitelisted(spam_profile.telegram_id)


async def test_auto_real_is_not_a_whitelist(db, real_profile):
    async with db.session() as session:
        repo = Repository(session)
        await repo.upsert_user(real_profile)
        await repo.record_decision(
            real_profile.telegram_id, Verdict.REAL, source=DecisionSource.AUTO
        )
        # Only a MANUAL "real" decision is a whitelist entry.
        assert not await repo.is_whitelisted(real_profile.telegram_id)


async def test_spam_user_ids_uses_latest_decision(db, spam_profile, real_profile):
    async with db.session() as session:
        repo = Repository(session)
        await repo.upsert_user(spam_profile)
        await repo.upsert_user(real_profile)
        await repo.record_decision(
            spam_profile.telegram_id, Verdict.SPAM, source=DecisionSource.AUTO
        )
        await repo.record_decision(
            real_profile.telegram_id, Verdict.SPAM, source=DecisionSource.AUTO
        )
        await repo.record_decision(
            real_profile.telegram_id, Verdict.REAL, source=DecisionSource.MANUAL, decided_by=7
        )
        ids = await repo.spam_user_ids()
    assert ids == [spam_profile.telegram_id]


async def test_recheck_cache(db, cfg, spam_profile):
    async with db.session() as session:
        repo = Repository(session)
        assert await repo.needs_recheck(spam_profile, recheck_days=30)

        await repo.upsert_user(spam_profile, touch_checked=True)
        result = score_user(spam_profile, cfg, nsfw_score=0.9)
        await repo.record_check(
            spam_profile.telegram_id, result, source=Performer.SCANNER, channel_id=-100
        )
        assert not await repo.needs_recheck(spam_profile, recheck_days=30)

        # A changed profile photo always forces a fresh check.
        changed = replace(spam_profile, photo_id="p-spam-2")
        assert await repo.needs_recheck(changed, recheck_days=30)


async def test_review_item_state_machine(db, spam_profile):
    async with db.session() as session:
        repo = Repository(session)
        await repo.upsert_user(spam_profile)
        item = await repo.create_review_item(
            spam_profile.telegram_id, channel_id=-100, check_id=None
        )
        await repo.attach_review_message(item.id, chat_id=-1001, message_id=42)

        assert await repo.has_pending_review(spam_profile.telegram_id)
        assert await repo.count_pending_reviews() == 1

        await repo.close_review_item(item.id, state="spam")
        assert not await repo.has_pending_review(spam_profile.telegram_id)
        assert await repo.count_pending_reviews() == 0

        stored = await repo.get_review_item(item.id)
        assert stored.state == "spam"
        assert stored.review_message_id == 42


async def test_comment_templates(db):
    async with db.session() as session:
        repo = Repository(session)
        text = "Kirish 👉 t.me/xxx"
        assert not await repo.touch_comment_template(text, flagged=True)
        # Same text, different punctuation/emoji: normalizes to the same hash.
        assert await repo.is_known_template("kirish t me xxx!!!")
        assert await repo.touch_comment_template(text, flagged=False)


async def test_actions_are_logged(db, spam_profile):
    async with db.session() as session:
        repo = Repository(session)
        await repo.upsert_user(spam_profile)
        await repo.record_action(
            spam_profile.telegram_id,
            ActionType.BAN,
            performed_by=Performer.BOT,
            status=ActionStatus.OK,
            channel_id=-100,
            reason="test",
        )
        summary = await repo.summary()
    assert summary["actions"]["ban"] == 1


async def test_summary_and_top_reasons(db, cfg, spam_profile, real_profile):
    async with db.session() as session:
        repo = Repository(session)
        for profile, nsfw in ((spam_profile, 0.97), (real_profile, 0.01)):
            await repo.upsert_user(profile, touch_checked=True)
            await repo.record_check(
                profile.telegram_id,
                score_user(profile, cfg, nsfw_score=nsfw),
                source=Performer.SCANNER,
                channel_id=-100,
            )
        summary = await repo.summary()
        reasons = await repo.top_reasons()

    assert summary["users"] == 2
    assert summary["checks_by_verdict"]["ban"] == 1
    assert summary["checks_by_verdict"]["ignore"] == 1
    assert reasons and reasons[0][1] >= 1


async def test_scan_run_resume(db):
    async with db.session() as session:
        repo = Repository(session)
        run = await repo.start_or_resume_run(-100, -200)
        await repo.mark_seen(run.id, 111)
        assert await repo.is_seen(run.id, 111)
        assert not await repo.is_seen(run.id, 222)
        await repo.update_run(run.id, cursor={"channel_queries": ["a"]}, stats={"seen": 1})

    async with db.session() as session:
        repo = Repository(session)
        # A restart must pick the same (still running) row up again.
        resumed = await repo.start_or_resume_run(-100, -200)
        assert resumed.id == run.id
        assert resumed.cursor["channel_queries"] == ["a"]
        assert await repo.seen_count(run.id) == 1


async def test_list_checked_users(db, cfg, spam_profile, real_profile, photoless_links_profile):
    async with db.session() as session:
        repo = Repository(session)
        for profile, nsfw in (
            (spam_profile, 0.97),
            (real_profile, 0.01),
            (photoless_links_profile, None),
        ):
            await repo.upsert_user(profile, touch_checked=True)
            await repo.record_check(
                profile.telegram_id,
                score_user(profile, cfg, nsfw_score=nsfw),
                source=Performer.SCANNER,
                channel_id=-100,
            )
        await repo.record_decision(
            spam_profile.telegram_id, Verdict.SPAM, source=DecisionSource.AUTO
        )

        spam_rows = await repo.list_checked_users(verdict="ban")
        review_rows = await repo.list_checked_users(verdict="review")
        all_rows = await repo.list_checked_users()

    assert [row["user_id"] for row in spam_rows] == [spam_profile.telegram_id]
    assert spam_rows[0]["decision"] == "spam"
    assert spam_rows[0]["reasons"]
    # No username -> the tg:// fallback link, always alongside the numeric id.
    assert spam_rows[0]["profile_url"] == f"tg://user?id={spam_profile.telegram_id}"

    assert [row["user_id"] for row in review_rows] == [photoless_links_profile.telegram_id]

    # Everything, highest score first.
    assert len(all_rows) == 3
    assert all_rows[0]["score"] >= all_rows[-1]["score"]
    real_row = next(r for r in all_rows if r["user_id"] == real_profile.telegram_id)
    assert real_row["profile_url"] == "https://t.me/jasur_dev"
    assert real_row["decision"] is None


async def test_list_filters(db, cfg, spam_profile, real_profile):
    async with db.session() as session:
        repo = Repository(session)
        for profile, nsfw in ((spam_profile, 0.97), (real_profile, 0.01)):
            await repo.upsert_user(profile, touch_checked=True)
            await repo.record_check(
                profile.telegram_id,
                score_user(profile, cfg, nsfw_score=nsfw),
                source=Performer.SCANNER,
                channel_id=-100,
            )
        # A manual decision takes the user out of the "still to decide" list.
        await repo.record_decision(
            spam_profile.telegram_id,
            Verdict.SPAM,
            source=DecisionSource.MANUAL,
            decided_by=42,
        )

        assert await repo.list_checked_users(min_score=0.9, limit=10)
        assert not await repo.list_checked_users(channel_id=-999)
        undecided = await repo.list_checked_users(undecided_only=True)
        assert spam_profile.telegram_id not in [row["user_id"] for row in undecided]
        assert await repo.list_checked_users(limit=1) != []
