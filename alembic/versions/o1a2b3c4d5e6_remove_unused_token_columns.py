"""Remove unused token tracking columns from chat_moderation_events

Revision ID: o1a2b3c4d5e6
Revises: n1a2b3c4d5e6
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'o1a2b3c4d5e6'
down_revision: Union[str, None] = 'n1a2b3c4d5e6'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("chat_moderation_events"):
        columns = {col["name"] for col in inspector.get_columns("chat_moderation_events")}

        if "ai_input_tokens" in columns:
            op.drop_column("chat_moderation_events", "ai_input_tokens")

        if "ai_output_tokens" in columns:
            op.drop_column("chat_moderation_events", "ai_output_tokens")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("chat_moderation_events"):
        columns = {col["name"] for col in inspector.get_columns("chat_moderation_events")}

        if "ai_input_tokens" not in columns:
            op.add_column(
                "chat_moderation_events",
                sa.Column("ai_input_tokens", sa.Integer(), nullable=True)
            )

        if "ai_output_tokens" not in columns:
            op.add_column(
                "chat_moderation_events",
                sa.Column("ai_output_tokens", sa.Integer(), nullable=True)
            )
