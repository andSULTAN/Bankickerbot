"""Policy: white/blacklist precedence and observe vs enforce."""

from __future__ import annotations

from core.policy import decide
from core.scoring import score_user


def _ban_result(cfg, profile):
    return score_user(profile, cfg, nsfw_score=0.99)


def test_whitelist_beats_everything(cfg, spam_profile):
    plan = decide(
        _ban_result(cfg, spam_profile),
        cfg,
        mode="enforce",
        whitelisted=True,
        blacklisted=True,
        has_message=True,
    )
    assert plan.source == "whitelist"
    assert not plan.ban and not plan.delete_message and not plan.review


def test_blacklist_bans_in_enforce(cfg):
    plan = decide(None, cfg, mode="enforce", blacklisted=True, has_message=True)
    assert plan.ban and plan.delete_message
    assert plan.source == "blacklist"


def test_blacklist_only_reports_in_observe(cfg):
    plan = decide(None, cfg, mode="observe", blacklisted=True, has_message=True)
    assert not plan.ban and not plan.delete_message
    assert plan.review and plan.withheld_by_observe


def test_high_score_bans_in_enforce(cfg, spam_profile):
    plan = decide(_ban_result(cfg, spam_profile), cfg, mode="enforce", has_message=True)
    assert plan.ban and plan.delete_message and plan.review  # review = undo notice


def test_high_score_only_reports_in_observe(cfg, spam_profile):
    plan = decide(_ban_result(cfg, spam_profile), cfg, mode="observe", has_message=True)
    assert not plan.ban
    assert plan.review and plan.withheld_by_observe


def test_review_range_does_not_delete_by_default(cfg, real_profile):
    result = score_user(real_profile, cfg, nsfw_score=0.75)
    plan = decide(result, cfg, mode="enforce", has_message=True)
    assert plan.review
    assert plan.delete_message is cfg.actions.delete_comment_on_review


def test_clean_user_is_left_alone(cfg, real_profile):
    result = score_user(real_profile, cfg, nsfw_score=0.01)
    plan = decide(result, cfg, mode="enforce", has_message=True)
    assert not plan.acts
