"""Give each agency its own crew rules.

`port_rules` holds one row per port, so an agent editing the rules wrote into
the record every agency berthed at that port shares — one agency's guidance
replaced what all the others were showing their crew.

Agent-authored rules move to `agent_profiles.agency_rules` and reach only the
vessels that agent manages. The port's own rules stay on `port_rules`, remain
superadmin-owned, and still apply to everyone.

Not backfilled: rules currently on `port_rules` cannot be attributed to
whichever agent last saved them, and guessing would hand one agency's wording
to another. They stay as port-wide rules, which is how they already behave.

Revision ID: b3d4e5f6g7h8
Revises: a2c3d4e5f6g7
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "b3d4e5f6g7h8"
down_revision = "a2c3d4e5f6g7"
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
