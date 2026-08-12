"""Pin a booking to its historical crew assignment.

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "m4n5o6p7q8r9"
down_revision = "l3m4n5o6p7q8"
branch_labels = None
depends_on = None

TABLE = "cab_bookings"
COLUMN = "crew_assignment_id"
INDEX = "ix_cab_bookings_crew_assignment_id"
CONSTRAINT = "fk_cab_bookings_crew_assignment_id"


def _inspector():
    return inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN not in columns:
        op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))
    inspector = _inspector()
    foreign_key = next(
        (
            fk for fk in inspector.get_foreign_keys(TABLE)
            if fk.get("constrained_columns") == [COLUMN]
        ),
        None,
    )
    if foreign_key is None:
        op.create_foreign_key(
            CONSTRAINT,
            TABLE,
            "crew_assignments",
            [COLUMN],
            ["id"],
            ondelete="SET NULL",
        )
    indexes = {index["name"] for index in _inspector().get_indexes(TABLE)}
    if INDEX not in indexes:
        op.create_index(INDEX, TABLE, [COLUMN])
    op.get_bind().execute(text("""
        UPDATE cab_bookings AS booking
        SET crew_assignment_id = resolved.assignment_id
        FROM (
            SELECT vessel_call_id, crew_profile_id, min(id) AS assignment_id
            FROM crew_assignments
            WHERE crew_profile_id IS NOT NULL
            GROUP BY vessel_call_id, crew_profile_id
            HAVING count(*) = 1
        ) AS resolved
        WHERE booking.crew_assignment_id IS NULL
          AND booking.vessel_call_id = resolved.vessel_call_id
          AND booking.crew_id = resolved.crew_profile_id
    """))


def downgrade() -> None:
    raise RuntimeError("Release 1 historical context cannot be safely downgraded")
