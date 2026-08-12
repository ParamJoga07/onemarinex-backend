"""Pin a cab booking to the vessel it was taken from.

``cab_bookings`` recorded only ``crew_id``, so a trip's ship had to be
inferred at read time from whoever booked it. A crew member who joins a second
vessel is on both manifests, so both ships matched them and every trip they had
ever taken followed them onto the new one, inflating trip counts and time-ashore
averages on a vessel where those trips never happened.

Nullable and not backfilled: existing rows have no reliable way to recover
which ship they belonged to, and guessing would re-create the defect. Readers
fall back to crew linkage when the column is NULL.

The first version of this migration accidentally reused revision
``a2c3d4e5f6g7``, which already belongs to the roster-unlink migration. It also
created the foreign key only when it created the column. The production startup
guard can create the column first, so the constraint must be checked
independently.

Revision ID: j1k2l3m4n5o6
Revises: i0k1l2m3n4o5
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "j1k2l3m4n5o6"
down_revision = "i0k1l2m3n4o5"
branch_labels = None
depends_on = None

TABLE = "cab_bookings"
COLUMN = "vessel_id"
INDEX = "ix_cab_bookings_vessel_id"
CONSTRAINT = "fk_cab_bookings_vessel_id"


def _inspector():
    return inspect(op.get_bind())


def _columns(table: str) -> set:
    inspector = _inspector()
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(table: str) -> set:
    inspector = _inspector()
    if table not in inspector.get_table_names():
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def _vessel_foreign_key():
    inspector = _inspector()
    if TABLE not in inspector.get_table_names():
        return None
    return next(
        (
            foreign_key
            for foreign_key in inspector.get_foreign_keys(TABLE)
            if foreign_key.get("constrained_columns") == [COLUMN]
            and foreign_key.get("referred_table") == "vessels"
            and foreign_key.get("referred_columns") == ["id"]
        ),
        None,
    )


def upgrade() -> None:
    # Idempotent: app/main.py carries a boot-time guard that may already have
    # created the column and index before Alembic reaches this revision.
    if not _columns(TABLE):
        return
    if COLUMN not in _columns(TABLE):
        op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
    if _vessel_foreign_key() is None:
        op.create_foreign_key(
            CONSTRAINT,
            TABLE,
            "vessels",
            [COLUMN],
            ["id"],
            ondelete="SET NULL",
        )
    if INDEX not in _indexes(TABLE):
        op.create_index(INDEX, TABLE, [COLUMN])


def downgrade() -> None:
    if COLUMN not in _columns(TABLE):
        return
    foreign_key = _vessel_foreign_key()
    if foreign_key is not None:
        constraint_name = foreign_key.get("name")
        if not constraint_name:
            raise RuntimeError("Cannot drop unnamed cab_bookings.vessel_id foreign key")
        op.drop_constraint(constraint_name, TABLE, type_="foreignkey")
    if INDEX in _indexes(TABLE):
        op.drop_index(INDEX, table_name=TABLE)
    op.drop_column(TABLE, COLUMN)
