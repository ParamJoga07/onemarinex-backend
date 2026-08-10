"""Pin a cab booking to the vessel it was taken from.

`cab_bookings` recorded only `crew_id`, so a trip's ship had to be inferred at
read time from whoever booked it. A crew member who joins a second vessel is on
both manifests, so both ships matched them and every trip they had ever taken
followed them onto the new one — inflating trip counts and time-ashore averages
on a vessel where those trips never happened.

Nullable and not backfilled: existing rows have no reliable way to recover which
ship they belonged to, and guessing would re-create the defect. Readers fall
back to crew linkage when the column is NULL.

Revision ID: a2c3d4e5f6g7
Revises: z1c2d3e4f5g6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "a2c3d4e5f6g7"
down_revision = "z1c2d3e4f5g6"
branch_labels = None
depends_on = None

TABLE = "cab_bookings"
COLUMN = "vessel_id"
INDEX = "ix_cab_bookings_vessel_id"


def _columns(table: str) -> set:
    inspector = inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(table: str) -> set:
    inspector = inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    # Idempotent: app/main.py carries a boot-time guard that applies the same
    # DDL, so either may have run first.
    if not _columns(TABLE):
        return
    if COLUMN not in _columns(TABLE):
        op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_cab_bookings_vessel_id", TABLE, "vessels",
            [COLUMN], ["id"], ondelete="SET NULL",
        )
    if INDEX not in _indexes(TABLE):
        op.create_index(INDEX, TABLE, [COLUMN])


def downgrade() -> None:
    if COLUMN not in _columns(TABLE):
        return
    if INDEX in _indexes(TABLE):
        op.drop_index(INDEX, table_name=TABLE)
    op.drop_constraint("fk_cab_bookings_vessel_id", TABLE, type_="foreignkey")
    op.drop_column(TABLE, COLUMN)
