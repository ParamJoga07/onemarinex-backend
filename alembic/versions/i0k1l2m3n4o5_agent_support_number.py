"""Give an agency its own support number.

The agent-facing Port Specific Rules editor wrote its "contact number" straight
onto port_rules.helpline_number — the row the superadmin owns and every agency
at that port shares. One agent saving their number replaced the port helpline
for everyone, and for crew of other agencies.

An agency's support number belongs to the agency, so it lives on agent_profiles.
port_rules.helpline_number stays superadmin-owned.

Revision ID: i0k1l2m3n4o5
Revises: h9j0k1l2m3n4
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "i0k1l2m3n4o5"
down_revision = "h9j0k1l2m3n4"
branch_labels = None
depends_on = None


def _columns(table):
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "support_number" not in _columns("agent_profiles"):
        op.add_column(
            "agent_profiles",
            sa.Column("support_number", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    if "support_number" in _columns("agent_profiles"):
        op.drop_column("agent_profiles", "support_number")
