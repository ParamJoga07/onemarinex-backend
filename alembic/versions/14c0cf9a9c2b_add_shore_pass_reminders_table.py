"""add shore_pass_reminders table

Revision ID: 14c0cf9a9c2b
Revises: 7f59f7c0b5f8
Create Date: 2026-07-26 20:28:11.527548

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '14c0cf9a9c2b'
down_revision: Union[str, None] = '7f59f7c0b5f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("shore_pass_reminders"):
        op.create_table(
            "shore_pass_reminders",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("shore_pass_id", sa.Integer(), sa.ForeignKey("shore_passes.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("reminder_type", sa.String(length=32), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("shore_pass_id", "reminder_type", name="uq_shore_pass_reminder"),
        )


def downgrade() -> None:
    if inspect(op.get_bind()).has_table("shore_pass_reminders"):
        op.drop_table("shore_pass_reminders")
