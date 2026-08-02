"""Add crew_chat_enabled and deleted_at columns for chat administration

Revision ID: q1a2b3c4d5e6
Revises: p1a2b3c4d5e6
Create Date: 2026-08-02 17:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'q1a2b3c4d5e6'
down_revision: Union[str, None] = 'p1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add crew_chat_enabled to chat_moderation_settings
    op.add_column('chat_moderation_settings', sa.Column('crew_chat_enabled', sa.Boolean(), server_default='true', nullable=False))


def downgrade() -> None:
    # Remove crew_chat_enabled from chat_moderation_settings
    op.drop_column('chat_moderation_settings', 'crew_chat_enabled')
