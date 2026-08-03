"""Add port timezone and trip-bound SOS context.

Revision ID: t1c2d3e4f5g6
Revises: s1c2d3e4f5g6
Create Date: 2026-08-02 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "t1c2d3e4f5g6"
down_revision: Union[str, Sequence[str], None] = "s1c2d3e4f5g6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table)}


def _has_cab_booking_fk() -> bool:
    return any(
        foreign_key.get("constrained_columns") == ["cab_booking_id"]
        and foreign_key.get("referred_table") == "cab_bookings"
        for foreign_key in inspect(op.get_bind()).get_foreign_keys("crew_sos_requests")
    )


def upgrade() -> None:
    if "timezone" not in _columns("port_rules"):
        op.add_column("port_rules", sa.Column("timezone", sa.String(length=64), nullable=True))

    # Existing supported ports are Indian ports except Dubai. Operators can
    # override this through Port Specific Rules for future locations.
    op.execute(
        """
        UPDATE port_rules
           SET timezone = CASE
               WHEN lower(port_name) LIKE '%dubai%' THEN 'Asia/Dubai'
               ELSE 'Asia/Kolkata'
           END
         WHERE timezone IS NULL OR btrim(timezone) = ''
        """
    )

    additions = {
        "cab_booking_id": sa.Column("cab_booking_id", sa.Integer(), nullable=True),
        "trip_id": sa.Column("trip_id", sa.String(length=64), nullable=True),
        "crew_email": sa.Column("crew_email", sa.String(length=255), nullable=True),
        "sos_email": sa.Column("sos_email", sa.String(length=255), nullable=True),
    }
    existing = _columns("crew_sos_requests")
    for name, column in additions.items():
        if name not in existing:
            op.add_column("crew_sos_requests", column)

    fk_name = "fk_crew_sos_requests_cab_booking_id"
    if not _has_cab_booking_fk():
        op.create_foreign_key(
            fk_name,
            "crew_sos_requests",
            "cab_bookings",
            ["cab_booking_id"],
            ["id"],
            ondelete="SET NULL",
        )

    index_names = _indexes("crew_sos_requests")
    if "ix_crew_sos_requests_cab_booking_id" not in index_names:
        op.create_index(
            "ix_crew_sos_requests_cab_booking_id",
            "crew_sos_requests",
            ["cab_booking_id"],
        )
    if "ix_crew_sos_requests_trip_id" not in index_names:
        op.create_index(
            "ix_crew_sos_requests_trip_id",
            "crew_sos_requests",
            ["trip_id"],
        )


def downgrade() -> None:
    index_names = _indexes("crew_sos_requests")
    if "ix_crew_sos_requests_trip_id" in index_names:
        op.drop_index("ix_crew_sos_requests_trip_id", table_name="crew_sos_requests")
    if "ix_crew_sos_requests_cab_booking_id" in index_names:
        op.drop_index("ix_crew_sos_requests_cab_booking_id", table_name="crew_sos_requests")

    for foreign_key in inspect(op.get_bind()).get_foreign_keys("crew_sos_requests"):
        if (
            foreign_key.get("constrained_columns") == ["cab_booking_id"]
            and foreign_key.get("referred_table") == "cab_bookings"
            and foreign_key.get("name")
        ):
            op.drop_constraint(
                foreign_key["name"], "crew_sos_requests", type_="foreignkey"
            )

    existing = _columns("crew_sos_requests")
    for name in ("sos_email", "crew_email", "trip_id", "cab_booking_id"):
        if name in existing:
            op.drop_column("crew_sos_requests", name)

    if "timezone" in _columns("port_rules"):
        op.drop_column("port_rules", "timezone")
