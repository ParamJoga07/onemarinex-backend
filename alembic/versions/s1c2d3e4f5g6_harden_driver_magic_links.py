"""Harden driver magic-link OTP and stop actions.

Revision ID: s1c2d3e4f5g6
Revises: r1b2c3d4e5f6
Create Date: 2026-08-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s1c2d3e4f5g6"
down_revision: Union[str, Sequence[str], None] = "r1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LINK_TABLE = "driver_magic_links"
EVENT_TABLE = "driver_magic_link_reach_events"
EVENT_STOP_CONSTRAINT = "uq_driver_magic_link_reach_event_stop"


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    table_names = set(inspector.get_table_names())

    if LINK_TABLE in table_names:
        existing_columns = {
            column["name"] for column in inspector.get_columns(LINK_TABLE)
        }
        if "otp_failed_attempts" not in existing_columns:
            op.add_column(
                LINK_TABLE,
                sa.Column(
                    "otp_failed_attempts",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                ),
            )
        if "otp_last_attempt_at" not in existing_columns:
            op.add_column(
                LINK_TABLE,
                sa.Column("otp_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            )
        if "otp_locked_until" not in existing_columns:
            op.add_column(
                LINK_TABLE,
                sa.Column("otp_locked_until", sa.DateTime(timezone=True), nullable=True),
            )

    if EVENT_TABLE in table_names:
        constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(EVENT_TABLE)
        }
        if EVENT_STOP_CONSTRAINT not in constraints:
            # Keep the newest record for any stop duplicated before this
            # idempotency constraint existed.
            op.execute(
                sa.text(
                    f"""
                    DELETE FROM {EVENT_TABLE}
                    WHERE id IN (
                        SELECT id
                        FROM (
                            SELECT
                                id,
                                ROW_NUMBER() OVER (
                                    PARTITION BY magic_link_id, stop_id
                                    ORDER BY reached_at DESC, id DESC
                                ) AS duplicate_rank
                            FROM {EVENT_TABLE}
                        ) ranked_events
                        WHERE duplicate_rank > 1
                    )
                    """
                )
            )
            op.create_unique_constraint(
                EVENT_STOP_CONSTRAINT,
                EVENT_TABLE,
                ["magic_link_id", "stop_id"],
            )


def downgrade() -> None:
    inspector = _inspector()
    table_names = set(inspector.get_table_names())

    if EVENT_TABLE in table_names:
        constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(EVENT_TABLE)
        }
        if EVENT_STOP_CONSTRAINT in constraints:
            op.drop_constraint(
                EVENT_STOP_CONSTRAINT,
                EVENT_TABLE,
                type_="unique",
            )

    if LINK_TABLE in table_names:
        existing_columns = {
            column["name"] for column in inspector.get_columns(LINK_TABLE)
        }
        for column_name in (
            "otp_locked_until",
            "otp_last_attempt_at",
            "otp_failed_attempts",
        ):
            if column_name in existing_columns:
                op.drop_column(LINK_TABLE, column_name)
