"""Scoring engine behaviour, including the photo-less safety rules."""

from __future__ import annotations

from core.enums import ScoreVerdict
from core.scoring import CommentContext, UserProfile, score_user


def test_spam_profile_is_banned(cfg, spam_profile):
    result = score_user(spam_profile, cfg, nsfw_score=0.97)
    assert result.verdict is ScoreVerdict.BAN
    assert result.score >= cfg.thresholds.ban
    assert any(reason.startswith("nsfw_photo") for reason in result.reasons)
    assert any(reason.startswith("bio_links") for reason in result.reasons)


def test_real_profile_is_ignored(cfg, real_profile):
    result = score_user(real_profile, cfg, nsfw_score=0.02)
    assert result.verdict is ScoreVerdict.IGNORE
    assert result.score < cfg.thresholds.review


def test_mild_nsfw_goes_to_review(cfg, real_profile):
    result = score_user(real_profile, cfg, nsfw_score=0.75)
    assert result.verdict is ScoreVerdict.REVIEW


def test_photoless_clean_profile_is_never_flagged(cfg, photoless_clean_profile):
    result = score_user(photoless_clean_profile, cfg)
    assert result.verdict is ScoreVerdict.IGNORE
    assert result.score <= cfg.photoless.max_score_without_strong
    # Weak signals must not even appear for a photo-less user.
    names = {signal.name for signal in result.signals}
    assert not names & set(cfg.weak_signals)


def test_photoless_ignores_nsfw_score(cfg, photoless_clean_profile):
    """A photo-less user cannot be hurt by a stray NSFW score."""
    result = score_user(photoless_clean_profile, cfg, nsfw_score=0.99)
    assert result.verdict is ScoreVerdict.IGNORE


def test_photoless_with_links_is_reviewed_not_banned(cfg, photoless_links_profile):
    result = score_user(photoless_links_profile, cfg)
    assert result.verdict is ScoreVerdict.REVIEW
    assert result.score < cfg.thresholds.ban
    assert not result.capped_photoless  # strong signals fired


def test_photoless_can_reach_ban_on_text_signals_alone(cfg, photoless_links_profile):
    """Only the strong text/link signals may push a photo-less user over the line."""
    comment = CommentContext(text="Kirish -> t.me/joinchat/abc", known_template=True)
    result = score_user(photoless_links_profile, cfg, comment=comment)
    assert result.verdict is ScoreVerdict.BAN


def test_comment_template_raises_score(cfg):
    profile = UserProfile(
        telegram_id=5_500_000_005, username="user", first_name="Ok", has_photo=True
    )
    plain = score_user(profile, cfg, nsfw_score=0.1, comment=CommentContext(text="Rahmat!"))
    templated = score_user(
        profile,
        cfg,
        nsfw_score=0.1,
        comment=CommentContext(text="Rahmat!", known_template=True),
    )
    assert templated.score > plain.score


def test_comment_timing_decays(cfg):
    profile = UserProfile(
        telegram_id=5_500_000_006, username="user", first_name="Ok", has_photo=True
    )
    fast = score_user(
        profile, cfg, nsfw_score=0.1, comment=CommentContext(text="salom", seconds_after_post=1)
    )
    slow = score_user(
        profile, cfg, nsfw_score=0.1, comment=CommentContext(text="salom", seconds_after_post=600)
    )
    assert fast.score > slow.score


def test_reasons_are_human_readable(cfg, spam_profile):
    result = score_user(spam_profile, cfg, nsfw_score=0.97)
    assert "nsfw_photo=0.97" in result.reasons_text
    payload = result.to_json()
    assert payload["verdict"] == "ban"
    assert payload["signals"]


def test_admin_ids_accepts_plain_and_empty_values():
    """`.env` holds ADMIN_IDS=111,222 - not JSON, and often empty at first."""
    from core.config import Settings

    assert Settings(admin_ids="111,222").admin_ids == [111, 222]
    assert Settings(admin_ids="111 222").admin_ids == [111, 222]
    assert Settings(admin_ids="").admin_ids == []
    assert Settings(admin_ids=[7]).is_admin(7)


def test_chat_id_conversion_between_telethon_and_bot_api():
    """The DB stores the Bot API form, Telethon hands us the bare id."""
    from core.ids import to_bot_api_id, to_telethon_id

    assert to_bot_api_id(1234567890) == -1001234567890
    assert to_telethon_id(-1001234567890) == 1234567890
    # Already-converted values must pass through unchanged (idempotent).
    assert to_bot_api_id(-1001234567890) == -1001234567890
    assert to_telethon_id(1234567890) == 1234567890
    # Legacy basic group.
    assert to_telethon_id(-123456789) == 123456789
