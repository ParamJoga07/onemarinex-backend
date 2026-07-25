"""Make optional crew_profiles columns nullable

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-07-25 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "i2j3k4l5m6n7"
down_revision = "h1i2j3k4l5m6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("crew_profiles", "date_of_birth", nullable=True)
    op.alter_column("crew_profiles", "current_port", nullable=True)
    op.alter_column("crew_profiles", "vessel", nullable=True)
    op.alter_column("crew_profiles", "ride_otp", nullable=True)
    op.alter_column("crew_profiles", "sos_email", nullable=True)


def downgrade() -> None:
    op.alter_column("crew_profiles", "sos_email", nullable=False)
    op.alter_column("crew_profiles", "ride_otp", nullable=False)
    op.alter_column("crew_profiles", "vessel", nullable=False)
    op.alter_column("crew_profiles", "current_port", nullable=False)
    op.alter_column("crew_profiles", "date_of_birth", nullable=False)
