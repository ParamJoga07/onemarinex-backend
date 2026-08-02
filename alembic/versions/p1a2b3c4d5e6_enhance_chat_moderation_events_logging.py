"""Enhance chat_moderation_events with Phase B/C/D fields

Revision ID: p1a2b3c4d5e6
Revises: o1a2b3c4d5e6
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'p1a2b3c4d5e6'
down_revision: Union[str, None] = 'o1a2b3c4d5e6'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns for Phase B (AI), Phase C (Policy), Phase D (Logging)
    try:
        op.add_column(
            "chat_moderation_events",
            sa.Column("ai_context_verdict", sa.String(length=16), nullable=True)
        )
    except Exception:
        pass

    try:
        op.add_column(
            "chat_moderation_events",
            sa.Column("category", sa.String(length=32), nullable=True)
        )
    except Exception:
        pass

    try:
        op.add_column(
            "chat_moderation_events",
            sa.Column("confidence", sa.Float(), server_default=sa.text('0.0'))
        )
    except Exception:
        pass

    try:
        op.add_column(
            "chat_moderation_events",
            sa.Column("reason", sa.Text(), server_default=sa.text("''"))
        )
    except Exception:
        pass

    try:
        op.add_column(
            "chat_moderation_events",
            sa.Column("moderation_layer", sa.String(length=16), nullable=True)
        )
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_column("chat_moderation_events", "ai_context_verdict")
    except Exception:
        pass

    try:
        op.drop_column("chat_moderation_events", "category")
    except Exception:
        pass

    try:
        op.drop_column("chat_moderation_events", "confidence")
    except Exception:
        pass

    try:
        op.drop_column("chat_moderation_events", "reason")
    except Exception:
        pass

    try:
        op.drop_column("chat_moderation_events", "moderation_layer")
    except Exception:
        pass
