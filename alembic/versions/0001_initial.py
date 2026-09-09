"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-01-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

VERDICT = sa.Enum("spam", "real", "skip", name="verdict", native_enum=False, length=16)
DECISION_SOURCE = sa.Enum(
    "auto", "manual", name="decision_source", native_enum=False, length=16
)
ACTION_TYPE = sa.Enum(
    "delete", "restrict", "ban", "unban", name="action_type", native_enum=False, length=16
)
PERFORMER = sa.Enum("scanner", "bot", name="performer", native_enum=False, length=16)
ACTION_STATUS = sa.Enum(
    "ok", "failed", "skipped", "dry_run", name="action_status", native_enum=False, length=16
)


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("title", sa.String(256)),
        sa.Column("username", sa.String(64)),
        sa.Column("linked_group_id", sa.BigInteger()),
        sa.Column("review_channel_id", sa.BigInteger()),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_channels_channel_id", "channels", ["channel_id"])

    op.create_table(
        "users",
        sa.Column("telegram_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("bio", sa.Text(), nullable=False, server_default=""),
        sa.Column("has_photo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("photo_id", sa.String(64)),
        sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_checked", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "checks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.telegram_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.BigInteger()),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("verdict", sa.String(16), nullable=False, server_default="ignore"),
        sa.Column("reasons", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("model_version", sa.String(32), nullable=False, server_default="1.0"),
        sa.Column("source", PERFORMER, nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_checks_user_id", "checks", ["user_id"])
    op.create_index("ix_checks_channel_id", "checks", ["channel_id"])
    op.create_index("ix_checks_checked_at", "checks", ["checked_at"])

    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.telegram_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.BigInteger()),
        sa.Column("verdict", VERDICT, nullable=False),
        sa.Column("source", DECISION_SOURCE, nullable=False),
        sa.Column("decided_by", sa.BigInteger()),
        sa.Column("note", sa.Text()),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_decisions_user_id", "decisions", ["user_id"])
    op.create_index("ix_decisions_decided_at", "decisions", ["decided_at"])

    op.create_table(
        "actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger()),
        sa.Column("action", ACTION_TYPE, nullable=False),
        sa.Column("performed_by", PERFORMER, nullable=False),
        sa.Column("status", ACTION_STATUS, nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_actions_user_id", "actions", ["user_id"])
    op.create_index("ix_actions_created_at", "actions", ["created_at"])

    op.create_table(
        "review_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger()),
        sa.Column("check_id", sa.Integer()),
        sa.Column("review_chat_id", sa.BigInteger()),
        sa.Column("review_message_id", sa.BigInteger()),
        sa.Column("comment_text", sa.Text()),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_review_items_user_id", "review_items", ["user_id"])
    op.create_index("ix_review_items_state", "review_items", ["state"])
    op.create_index("ix_review_items_state_user", "review_items", ["state", "user_id"])

    op.create_table(
        "comment_templates",
        sa.Column("hash", sa.String(64), primary_key=True),
        sa.Column("sample", sa.Text(), nullable=False, server_default=""),
        sa.Column("times_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flagged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "scan_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger()),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("cursor", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("stats", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_scan_runs_channel_id", "scan_runs", ["channel_id"])
    op.create_index("ix_scan_runs_status", "scan_runs", ["status"])

    op.create_table(
        "scan_seen",
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("scan_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "user_id", name="uq_scan_seen"),
    )


def downgrade() -> None:
    op.drop_table("scan_seen")
    op.drop_table("scan_runs")
    op.drop_table("comment_templates")
    op.drop_table("review_items")
    op.drop_table("actions")
    op.drop_table("decisions")
    op.drop_table("checks")
    op.drop_table("users")
    op.drop_table("channels")
