"""Enhance chat_moderation_events with Phase B/C/D fields

Revision ID: p1a2b3c4d5e6
Revises: o1a2b3c4d5e6
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'p1a2b3c4d5e6'
down_revision: Union[str, None] = 'o1a2b3c4d5e6'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Add new columns for Phase B (AI), Phase C (Policy), Phase D (Logging)
    if inspector.has_table("chat_moderation_events"):
        # Level 2: AI Context Verdict
        if not inspector.has_column("chat_moderation_events", "ai_context_verdict"):
            op.add_column(
                "chat_moderation_events",
                sa.Column("ai_context_verdict", sa.String(length=16), nullable=True)
            )

        # Level 3: Policy Decision
        if not inspector.has_column("chat_moderation_events", "category"):
            op.add_column(
                "chat_moderation_events",
                sa.Column("category", sa.String(length=32), nullable=True)
            )

        if not inspector.has_column("chat_moderation_events", "confidence"):
            op.add_column(
                "chat_moderation_events",
                sa.Column("confidence", sa.Float(), server_default=sa.text('0.0'))
            )

        if not inspector.has_column("chat_moderation_events", "reason"):
            op.add_column(
                "chat_moderation_events",
                sa.Column("reason", sa.Text(), server_default=sa.text("''"))
            )

        if not inspector.has_column("chat_moderation_events", "moderation_layer"):
            op.add_column(
                "chat_moderation_events",
                sa.Column("moderation_layer", sa.String(length=16), nullable=True)
            )


def downgrade() -> None:
    inspector = inspect(op.get_bind())

    if inspector.has_table("chat_moderation_events"):
        if inspector.has_column("chat_moderation_events", "ai_context_verdict"):
            op.drop_column("chat_moderation_events", "ai_context_verdict")

        if inspector.has_column("chat_moderation_events", "category"):
            op.drop_column("chat_moderation_events", "category")

        if inspector.has_column("chat_moderation_events", "confidence"):
            op.drop_column("chat_moderation_events", "confidence")

        if inspector.has_column("chat_moderation_events", "reason"):
            op.drop_column("chat_moderation_events", "reason")

        if inspector.has_column("chat_moderation_events", "moderation_layer"):
            op.drop_column("chat_moderation_events", "moderation_layer")
