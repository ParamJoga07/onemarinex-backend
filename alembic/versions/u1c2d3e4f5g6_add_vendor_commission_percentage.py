"""Add vendor commission percentage used for crew-list ranking.

Revision ID: u1c2d3e4f5g6
Revises: t1c2d3e4f5g6
Create Date: 2026-08-02 19:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "u1c2d3e4f5g6"
down_revision: Union[str, Sequence[str], None] = "t1c2d3e4f5g6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "ix_vendors_port_category_commission"


def _columns() -> dict[str, dict]:
    return {
        column["name"]: column
        for column in inspect(op.get_bind()).get_columns("vendors")
    }


def _indexes() -> set[str]:
    return {
        index["name"]
        for index in inspect(op.get_bind()).get_indexes("vendors")
    }


def upgrade() -> None:
    if "commission_percentage" not in _columns():
        op.add_column(
            "vendors",
            sa.Column(
                "commission_percentage",
                sa.Numeric(precision=5, scale=2),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    if INDEX_NAME not in _indexes():
        op.create_index(
            INDEX_NAME,
            "vendors",
            ["port_id", "category", "commission_percentage"],
        )


def downgrade() -> None:
    if INDEX_NAME in _indexes():
        op.drop_index(INDEX_NAME, table_name="vendors")
    if "commission_percentage" in _columns():
        op.drop_column("vendors", "commission_percentage")
