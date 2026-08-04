"""Clear placeholder helpline numbers from existing cab bookings

The helpline used to be stamped on every booking from a hardcoded placeholder
rather than the port's configured number. Crew saw it on the trip screen as a
real 24/7 support line. Null it out so readers fall back to agent_number.

Revision ID: v1c2d3e4f5g6
Revises: u1c2d3e4f5g6
Create Date: 2026-08-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "v1c2d3e4f5g6"
down_revision = "u1c2d3e4f5g6"
branch_labels = None
depends_on = None

PLACEHOLDER_HELPLINES = ("+91 1800-HEYPORTS", "+91 1800 425 1234")


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE cab_bookings SET helpline_number = NULL "
            "WHERE helpline_number IN :placeholders"
        ).bindparams(
            sa.bindparam("placeholders", value=PLACEHOLDER_HELPLINES, expanding=True)
        )
    )
    op.execute(
        sa.text(
            "UPDATE port_rules SET helpline_number = NULL "
            "WHERE helpline_number IN :placeholders"
        ).bindparams(
            sa.bindparam("placeholders", value=PLACEHOLDER_HELPLINES, expanding=True)
        )
    )


def downgrade() -> None:
    # The original values were placeholders, not data worth restoring.
    pass
