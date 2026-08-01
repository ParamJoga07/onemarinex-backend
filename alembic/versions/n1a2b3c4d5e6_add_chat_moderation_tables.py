"""Add chat moderation tables

Revision ID: n1a2b3c4d5e6
Revises: m1a2b3c4d5e6
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'n1a2b3c4d5e6'
down_revision: Union[str, None] = 'm1a2b3c4d5e6'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("chat_restricted_words"):
        op.create_table(
            "chat_restricted_words",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("word", sa.String(length=128), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=True),
            sa.Column("is_phrase", sa.Boolean(), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text('true'), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("word"),
        )
        op.create_index("ix_chat_restricted_words_id", "chat_restricted_words", ["id"])
        op.create_index("ix_chat_restricted_words_word", "chat_restricted_words", ["word"])

    if not inspector.has_table("chat_moderation_events"):
        op.create_table(
            "chat_moderation_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("port_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("chat_message_id", sa.Integer(), nullable=True),
            sa.Column("raw_message", sa.Text(), nullable=False),
            sa.Column("normalized_message", sa.Text(), nullable=False),
            sa.Column("decision", sa.String(length=16), nullable=False),
            sa.Column("rejected_by", sa.String(length=32), nullable=True),
            sa.Column("reason_code", sa.String(length=48), nullable=True),
            sa.Column("matched_term", sa.String(length=128), nullable=True),
            sa.Column("ai_route", sa.String(length=24), nullable=True),
            sa.Column("ai_model", sa.String(length=64), nullable=True),
            sa.Column("ai_latency_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["chat_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["port_id"], ["ports.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_chat_moderation_events_id", "chat_moderation_events", ["id"])
        op.create_index("ix_chat_moderation_events_port_id", "chat_moderation_events", ["port_id"])
        op.create_index("ix_chat_moderation_events_user_id", "chat_moderation_events", ["user_id"])

    if not inspector.has_table("chat_moderation_settings"):
        op.create_table(
            "chat_moderation_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("max_message_length", sa.Integer(), server_default=sa.text('200')),
            sa.Column("rate_limit_count", sa.Integer(), server_default=sa.text('5')),
            sa.Column("rate_limit_window_seconds", sa.Integer(), server_default=sa.text('10')),
            sa.Column("duplicate_window_seconds", sa.Integer(), server_default=sa.text('60')),
            sa.Column("language_ai_enabled", sa.Boolean(), server_default=sa.text('true')),
            sa.Column("moderation_ai_enabled", sa.Boolean(), server_default=sa.text('true')),
            sa.Column("fail_closed", sa.Boolean(), server_default=sa.text('true')),
            sa.Column("block_external_links", sa.Boolean(), server_default=sa.text('false')),
            sa.Column("block_contact_info", sa.Boolean(), server_default=sa.text('false')),
            sa.Column("block_payment_info", sa.Boolean(), server_default=sa.text('false')),
            sa.Column("updated_by", sa.String(length=255), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_chat_moderation_settings_id", "chat_moderation_settings", ["id"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())

    if inspector.has_table("chat_moderation_settings"):
        op.drop_table("chat_moderation_settings")

    if inspector.has_table("chat_moderation_events"):
        op.drop_table("chat_moderation_events")

    if inspector.has_table("chat_restricted_words"):
        op.drop_table("chat_restricted_words")
