"""Enums shared by the scoring engine, the DB models and both components."""

from __future__ import annotations

from enum import Enum


class Verdict(str, Enum):
    SPAM = "spam"
    REAL = "real"
    SKIP = "skip"


class ScoreVerdict(str, Enum):
    """What the scoring engine suggests, before any policy/mode is applied."""

    BAN = "ban"
    REVIEW = "review"
    IGNORE = "ignore"


class DecisionSource(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class ActionType(str, Enum):
    DELETE = "delete"
    RESTRICT = "restrict"
    BAN = "ban"
    UNBAN = "unban"


class Performer(str, Enum):
    SCANNER = "scanner"
    BOT = "bot"


class ActionStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"
