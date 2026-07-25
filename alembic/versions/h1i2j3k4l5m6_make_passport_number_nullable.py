"""Make passport_number nullable in crew_profiles

Revision ID: h1i2j3k4l5m6
Revises: g9h0i1j2k3l4
Create Date: 2026-07-25 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "h1i2j3k4l5m6"
down_revision = "g9h0i1j2k3l4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("crew_profiles", "passport_number", nullable=True)


def downgrade() -> None:
    op.alter_column("crew_profiles", "passport_number", nullable=False)
