"""Add shore_pass_valid_upto to vessels

The shore-pass expiry was captured per crew member, one at a time. It is really
a property of the port call: one date for the whole crew, with an individual
override where needed. This adds the vessel-level master date; the per-crew
column stays and continues to hold the effective date for each person.

Revision ID: x1c2d3e4f5g6
Revises: w1c2d3e4f5g6
Create Date: 2026-08-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "x1c2d3e4f5g6"
down_revision = "w1c2d3e4f5g6"
branch_labels = None
depends_on = None


def _columns(table: str) -> set:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "shore_pass_valid_upto" not in _columns("vessels"):
        op.add_column(
            "vessels",
            sa.Column("shore_pass_valid_upto", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if "shore_pass_valid_upto" in _columns("vessels"):
        op.drop_column("vessels", "shore_pass_valid_upto")
