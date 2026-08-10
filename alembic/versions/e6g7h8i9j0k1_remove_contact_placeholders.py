"""remove retired booking contact placeholders

Revision ID: e6g7h8i9j0k1
Revises: d5f6g7h8i9j0
"""

from alembic import op
import sqlalchemy as sa


revision = "e6g7h8i9j0k1"
down_revision = "d5f6g7h8i9j0"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "cab_bookings" in tables:
        bind.execute(sa.text(
            "UPDATE cab_bookings SET agent_number = NULL "
            "WHERE regexp_replace(coalesce(agent_number, ''), '[^0-9]', '', 'g') "
            "IN ('919876543251', '9198765403251', '919876542064')"
        ))


def downgrade():
    # Invented support contacts must never be restored.
    pass
