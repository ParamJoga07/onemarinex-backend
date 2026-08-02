"""Persist OTP verification for driver magic links.

Revision ID: r1b2c3d4e5f6
Revises: a8e1c2d3f4b5, q1a2b3c4d5e6
Create Date: 2026-08-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = (
    "a8e1c2d3f4b5",
    "q1a2b3c4d5e6",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "driver_magic_links"


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    if TABLE not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if "otp_verified_at" not in existing_columns:
        op.add_column(
            TABLE,
            sa.Column("otp_verified_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    inspector = _inspector()
    if TABLE not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if "otp_verified_at" in existing_columns:
        op.drop_column(TABLE, "otp_verified_at")
