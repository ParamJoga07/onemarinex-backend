"""Add agency_logo_url to agent_profiles

The agency logo and the contact person's profile picture are different things:
the logo is printed at the top of the incident and shore-leave PDF reports,
while profile_image is the person's avatar on the profile page. They were
sharing one column.

Revision ID: w1c2d3e4f5g6
Revises: v1c2d3e4f5g6
Create Date: 2026-08-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "w1c2d3e4f5g6"
down_revision = "v1c2d3e4f5g6"
branch_labels = None
depends_on = None


def _columns(table: str) -> set:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "agency_logo_url" not in _columns("agent_profiles"):
        op.add_column(
            "agent_profiles",
            sa.Column("agency_logo_url", sa.String(length=512), nullable=True),
        )


def downgrade() -> None:
    if "agency_logo_url" in _columns("agent_profiles"):
        op.drop_column("agent_profiles", "agency_logo_url")
