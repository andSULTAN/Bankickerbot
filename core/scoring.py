"""Weighted-signal scoring engine.

The engine is pure: it takes a profile snapshot (plus an already-computed NSFW
probability and an optional comment context) and returns a score in [0, 1] with
a human-readable reason list. No I/O, no Telegram, no DB - so it is trivially
unit-testable and shared by the scanner and the bot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.config import ScoringConfig
from core.enums import ScoreVerdict
from core.text_utils import find_emojis, find_keywords, find_patterns

# Bounds for the very weak "account id magnitude" heuristic: Telegram ids grow
# over time, so a huge id means a freshly created account.
ID_LOW = 1_000_000_000
ID_HIGH = 6_000_000_000


@dataclass(slots=True)
class UserProfile:
    """Everything the engine needs to know about a Telegram user."""

    telegram_id: int
    username: str | None = None
    first_name: str = ""
    last_name: str = ""
    bio: str = ""
    has_photo: bool = False
    photo_id: str | None = None
    is_premium: bool = False

    @property
    def display_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part).strip()


@dataclass(slots=True)
class CommentContext:
    """Bot-only context: the comment that triggered the check."""

    text: str = ""
    seconds_after_post: float | None = None
    # True when the same normalized text was already seen from another flagged user.
    known_template: bool = False


@dataclass(slots=True)
class Signal:
    name: str
    value: float           # 0..1, how strongly the signal fired
    weight: float          # from scoring.yaml
    detail: str = ""       # e.g. "t.me/, 18+"

    @property
    def contribution(self) -> float:
        return self.value * self.weight


@dataclass(slots=True)
class ScoreResult:
    score: float
    verdict: ScoreVerdict
    signals: list[Signal] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    version: str = "1.0"
    capped_photoless: bool = False

    @property
    def reasons_text(self) -> str:
        return ", ".join(self.reasons) if self.reasons else "-"

    def to_json(self) -> dict:
        return {
            "score": round(self.score, 4),
            "verdict": self.verdict.value,
            "capped_photoless": self.capped_photoless,
            "signals": [
                {
                    "name": s.name,
                    "value": round(s.value, 4),
                    "weight": s.weight,
                    "contribution": round(s.contribution, 4),
                    "detail": s.detail,
                }
                for s in self.signals
            ],
            "reasons": self.reasons,
        }


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _stacked(hits: int, first: float, extra: float) -> float:
    """First match is worth `first`, every additional one adds `extra` (max 1.0)."""
    if hits <= 0:
        return 0.0
    return _clamp(first + extra * (hits - 1))


# --- individual signals -----------------------------------------------------


def signal_nsfw_photo(profile: UserProfile, nsfw_score: float | None) -> float:
    # Rule: a user without a profile photo is assumed to be a real person.
    if not profile.has_photo or nsfw_score is None:
        return 0.0
    return _clamp(nsfw_score)


def signal_bio_links(profile: UserProfile, cfg: ScoringConfig) -> tuple[float, str]:
    hits = find_patterns(profile.bio, cfg.bio.url_patterns)
    hits += find_keywords(profile.bio, cfg.bio.keywords)
    value = _stacked(len(hits), cfg.bio.match_value, cfg.bio.extra_match_value)
    return value, ", ".join(hits[:4])


def signal_name_pattern(profile: UserProfile, cfg: ScoringConfig) -> tuple[float, str]:
    name = f"{profile.first_name} {profile.last_name}".strip()
    hits = find_patterns(name, cfg.name.patterns)
    hits += find_emojis(name, cfg.name.emojis)
    value = _stacked(len(hits), cfg.name.match_value, cfg.name.extra_match_value)
    return value, ", ".join(hits[:4])


def signal_no_username(profile: UserProfile) -> float:
    return 0.0 if profile.username else 1.0


def signal_premium(profile: UserProfile) -> float:
    return 1.0 if profile.is_premium else 0.0


def signal_id_magnitude(profile: UserProfile) -> float:
    if profile.telegram_id <= ID_LOW:
        return 0.0
    return _clamp((profile.telegram_id - ID_LOW) / (ID_HIGH - ID_LOW))


def signal_comment_pattern(
    comment: CommentContext | None, cfg: ScoringConfig
) -> tuple[float, str]:
    if comment is None or not comment.text:
        return 0.0, ""
    if comment.known_template:
        return _clamp(cfg.comment.template_value), "known_template"
    hits = find_patterns(comment.text, cfg.comment.url_patterns)
    if hits:
        return _clamp(cfg.comment.link_value), ", ".join(hits[:3])
    return 0.0, ""


def signal_comment_timing(comment: CommentContext | None, cfg: ScoringConfig) -> float:
    if comment is None or comment.seconds_after_post is None:
        return 0.0
    window = max(1, cfg.comment.fast_reply_seconds)
    if comment.seconds_after_post < 0:
        return 0.0
    if comment.seconds_after_post >= window:
        return 0.0
    # Linear: instant reply = 1.0, a reply at the edge of the window = 0.0.
    return _clamp(1.0 - comment.seconds_after_post / window)


# --- engine -----------------------------------------------------------------


def score_user(
    profile: UserProfile,
    cfg: ScoringConfig,
    *,
    nsfw_score: float | None = None,
    comment: CommentContext | None = None,
) -> ScoreResult:
    """Compute the spam score of a user."""
    weights = cfg.weights
    raw: list[Signal] = []

    bio_value, bio_detail = signal_bio_links(profile, cfg)
    name_value, name_detail = signal_name_pattern(profile, cfg)
    comment_value, comment_detail = signal_comment_pattern(comment, cfg)

    raw.append(
        Signal("nsfw_photo", signal_nsfw_photo(profile, nsfw_score), weights.get("nsfw_photo", 0.0))
    )
    raw.append(Signal("bio_links", bio_value, weights.get("bio_links", 0.0), bio_detail))
    raw.append(Signal("name_pattern", name_value, weights.get("name_pattern", 0.0), name_detail))
    raw.append(
        Signal(
            "comment_pattern",
            comment_value,
            weights.get("comment_pattern", 0.0),
            comment_detail,
        )
    )
    raw.append(
        Signal(
            "comment_timing",
            signal_comment_timing(comment, cfg),
            weights.get("comment_timing", 0.0),
        )
    )
    raw.append(Signal("no_username", signal_no_username(profile), weights.get("no_username", 0.0)))
    raw.append(Signal("premium", signal_premium(profile), weights.get("premium", 0.0)))
    raw.append(
        Signal("id_magnitude", signal_id_magnitude(profile), weights.get("id_magnitude", 0.0))
    )

    photoless = not profile.has_photo
    weak = set(cfg.weak_signals)
    strong = set(cfg.photoless.strong_signals)

    signals: list[Signal] = []
    for signal in raw:
        if photoless and cfg.photoless.drop_weak_signals and signal.name in weak:
            continue
        signals.append(signal)

    score = _clamp(sum(signal.contribution for signal in signals))

    capped = False
    if photoless:
        strong_fired = any(s.value > 0 for s in signals if s.name in strong)
        if not strong_fired:
            limit = cfg.photoless.max_score_without_strong
            if score > limit:
                score = limit
                capped = True

    reasons = _build_reasons(signals, photoless=photoless, capped=capped)
    verdict = classify(score, cfg)
    return ScoreResult(
        score=score,
        verdict=verdict,
        signals=signals,
        reasons=reasons,
        version=cfg.version,
        capped_photoless=capped,
    )


def _build_reasons(signals: list[Signal], *, photoless: bool, capped: bool) -> list[str]:
    reasons: list[str] = []
    for signal in signals:
        if signal.value <= 0 or signal.weight == 0:
            continue
        text = f"{signal.name}={signal.value:.2f}"
        if signal.detail:
            text += f" ({signal.detail})"
        reasons.append(text)
    if photoless:
        reasons.append("no_photo (haqiqiy odam deb qaraldi)")
    if capped:
        reasons.append("photoless_cap")
    return reasons


def classify(score: float, cfg: ScoringConfig) -> ScoreVerdict:
    if score >= cfg.thresholds.ban:
        return ScoreVerdict.BAN
    if score >= cfg.thresholds.review:
        return ScoreVerdict.REVIEW
    return ScoreVerdict.IGNORE
