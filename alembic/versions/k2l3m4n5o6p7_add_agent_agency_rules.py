"""Give each agency its own crew rules.

``port_rules`` holds one row per port, so agent-authored rules belong on the
agent profile rather than the shared port record. The port's own rules remain
superadmin-owned and continue to apply to every agency at that port.

Existing port rules are not backfilled because the data does not identify which
agent, if any, authored them. Guessing would incorrectly assign shared guidance
to one agency, so those rows retain their current port-wide meaning.

The first version of this migration accidentally reused revision
``b3d4e5f6g7h8``, which already belongs to notification audiences. This
revision follows the booking-vessel repair and restores one linear migration
head.

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "k2l3m4n5o6p7"
down_revision = "j1k2l3m4n5o6"
branch_labels = None
depends_on = None

TABLE = "agent_profiles"
COLUMN = "agency_rules"


def _columns(table: str) -> set:
    inspector = inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    # Idempotent: app/main.py carries a boot guard applying the same DDL.
    columns = _columns(TABLE)
    if not columns or COLUMN in columns:
        return
    op.add_column(TABLE, sa.Column(COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    if COLUMN in _columns(TABLE):
        op.drop_column(TABLE, COLUMN)
