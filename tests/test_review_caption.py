"""Review message formatting (profile link, id, reasons, escaping)."""

from __future__ import annotations

from core import strings
from core.review import build_caption, review_keyboard
from core.scoring import score_user


def test_caption_uses_username_link(cfg, real_profile):
    result = score_user(real_profile, cfg, nsfw_score=0.65)
    caption = build_caption(real_profile, result, title="T", channel_title="Kanal")
    assert 'https://t.me/jasur_dev' in caption
    assert f"ID: <code>{real_profile.telegram_id}</code>" in caption
    assert "Ball:" in caption


def test_caption_falls_back_to_tg_user_link(cfg, photoless_clean_profile):
    result = score_user(photoless_clean_profile, cfg)
    caption = build_caption(photoless_clean_profile, result, title="T")
    assert f'tg://user?id={photoless_clean_profile.telegram_id}' in caption
    assert strings.REVIEW_NO_PHOTO in caption


def test_caption_escapes_user_text(cfg, spam_profile):
    profile = spam_profile
    profile.bio = "<script>alert(1)</script>"
    caption = build_caption(profile, None, title="T", comment_text="<b>hack</b>")
    assert "<script>" not in caption
    assert "&lt;script&gt;" in caption


def test_caption_is_clipped_to_photo_limit(cfg, spam_profile):
    spam_profile.bio = "x" * 5000
    caption = build_caption(spam_profile, None, title="T")
    assert len(caption) <= 1024


def test_keyboard_has_three_buttons():
    markup = review_keyboard(7)
    buttons = markup.inline_keyboard[0]
    assert [b.text for b in buttons] == [strings.BTN_SPAM, strings.BTN_REAL, strings.BTN_SKIP]
    assert all(b.callback_data.endswith(":7") for b in buttons)
