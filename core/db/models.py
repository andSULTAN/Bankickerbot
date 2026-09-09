"""SQLAlchemy models.

Privacy note: profile photos are never stored. Only photo ids, scores and the
reason lists survive a check.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base
from core.enums import ActionStatus, ActionType, DecisionSource, Performer, Verdict


def _enum(python_enum, name: str) -> SAEnum:
    # values_callable keeps the DB values lowercase ("spam"), not the member names.
    return SAEnum(
        python_enum,
        name=name,
        values_callable=lambda e: [member.value for member in e],
        native_enum=False,
        length=16,
    )


class Channel(Base):
    """A protected channel plus its linked discussion group and review channel."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(256))
    username: Mapped[str | None] = mapped_column(String(64))
    linked_group_id: Mapped[int | None] = mapped_column(BigInteger)
    review_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    """Last known snapshot of a Telegram user."""

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    first_name: Mapped[str] = mapped_column(String(256), default="")
    last_name: Mapped[str] = mapped_column(String(256), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    has_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Photo identity, as a string: Telethon writes the numeric photo id,
    # the Bot API side writes file_unique_id. Only compared for equality.
    photo_id: Mapped[str | None] = mapped_column(String(64))
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    checks: Mapped[list[Check]] = relationship(back_populates="user")
    decisions: Mapped[list[Decision]] = relationship(back_populates="user")

    @property
    def display_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip() or "(ismsiz)"


class Check(Base):
    """One scoring run against one user."""

    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    verdict: Mapped[str] = mapped_column(String(16), default="ignore")
    reasons: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(32), default="1.0")
    source: Mapped[Performer] = mapped_column(_enum(Performer, "performer"))
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    user: Mapped[User] = relationship(back_populates="checks")


class Decision(Base):
    """A verdict about a user. The latest manual decision wins (white/blacklist)."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    verdict: Mapped[Verdict] = mapped_column(_enum(Verdict, "verdict"))
    source: Mapped[DecisionSource] = mapped_column(_enum(DecisionSource, "decision_source"))
    decided_by: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    user: Mapped[User] = relationship(back_populates="decisions")


class Action(Base):
    """Audit log of everything destructive (or attempted) we ever did."""

    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[ActionType] = mapped_column(_enum(ActionType, "action_type"))
    performed_by: Mapped[Performer] = mapped_column(_enum(Performer, "performer"))
    status: Mapped[ActionStatus] = mapped_column(_enum(ActionStatus, "action_status"))
    reason: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ReviewItem(Base):
    """A profile posted to the review channel, waiting for a manual verdict."""

    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    check_id: Mapped[int | None] = mapped_column(Integer)
    review_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    review_message_id: Mapped[int | None] = mapped_column(BigInteger)
    comment_text: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_review_items_state_user", "state", "user_id"),)


class CommentTemplate(Base):
    """Normalized comment hashes, used for the `comment_pattern` signal."""

    __tablename__ = "comment_templates"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    sample: Mapped[str] = mapped_column(Text, default="")
    times_seen: Mapped[int] = mapped_column(Integer, default=0)
    flagged_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ScanRun(Base):
    """Checkpoint of a scanner run so a restart resumes instead of starting over."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    # {"done_queries": [...], "seen_ids": N, "phase": "channel"|"group"}
    cursor: Mapped[dict] = mapped_column(JSON, default=dict)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScanSeen(Base):
    """Users already processed inside a scan run (resume support)."""

    __tablename__ = "scan_seen"

    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scan_runs.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("run_id", "user_id", name="uq_scan_seen"),)
