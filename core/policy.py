"""Policy layer: turns a score + known decisions + run mode into an action plan.

This is the single place that answers "what should we actually do with this
user?", so the scanner and the bot can never drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.config import Mode, ScoringConfig
from core.enums import ScoreVerdict
from core.scoring import ScoreResult


@dataclass(slots=True)
class Plan:
    ban: bool = False
    delete_message: bool = False
    review: bool = False
    # Why we decided this: "whitelist" | "blacklist" | "score" | "below_threshold"
    source: str = "score"
    reason: str = ""
    # True when enforcement was withheld only because we run in observe mode.
    withheld_by_observe: bool = False

    @property
    def acts(self) -> bool:
        return self.ban or self.delete_message or self.review


def decide(
    result: ScoreResult | None,
    cfg: ScoringConfig,
    *,
    mode: Mode,
    whitelisted: bool = False,
    blacklisted: bool = False,
    has_message: bool = False,
) -> Plan:
    """Decide what to do. `mode="observe"` never produces destructive actions."""
    enforce = mode == "enforce"

    if whitelisted:
        return Plan(source="whitelist", reason="oq ro'yxatda")

    if blacklisted:
        if enforce:
            return Plan(
                ban=True,
                delete_message=has_message,
                source="blacklist",
                reason="qora ro'yxatda",
            )
        return Plan(
            review=True,
            source="blacklist",
            reason="qora ro'yxatda (observe rejimi: ban qilinmadi)",
            withheld_by_observe=True,
        )

    if result is None:
        return Plan(source="score", reason="tekshiruv yo'q")

    if result.verdict == ScoreVerdict.BAN:
        if enforce:
            return Plan(
                ban=True,
                delete_message=has_message,
                review=True,  # a short notice so the admin can undo it
                source="score",
                reason=result.reasons_text,
            )
        return Plan(
            review=True,
            source="score",
            reason=result.reasons_text,
            withheld_by_observe=True,
        )

    if result.verdict == ScoreVerdict.REVIEW:
        return Plan(
            review=True,
            delete_message=has_message and enforce and cfg.actions.delete_comment_on_review,
            source="score",
            reason=result.reasons_text,
        )

    return Plan(source="below_threshold", reason=result.reasons_text)
