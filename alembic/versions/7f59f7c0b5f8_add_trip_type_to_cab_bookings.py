"""add trip_type to cab_bookings

Revision ID: 7f59f7c0b5f8
Revises: i2j3k4l5m6n7
Create Date: 2026-07-26 18:56:09.710014

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '7f59f7c0b5f8'
down_revision: Union[str, None] = 'i2j3k4l5m6n7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return column in [c["name"] for c in insp.get_columns(table)]


def upgrade() -> None:
    if not column_exists("cab_bookings", "trip_type"):
        op.add_column("cab_bookings", sa.Column("trip_type", sa.String(length=32), nullable=True))


def downgrade() -> None:
    if column_exists("cab_bookings", "trip_type"):
        op.drop_column("cab_bookings", "trip_type")
