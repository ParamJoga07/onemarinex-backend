"""Audit manual historical-event reconciliation.

Revision ID: o6p7q8r9s0t1
Revises: n5o6p7q8r9s0
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "o6p7q8r9s0t1"
down_revision = "n5o6p7q8r9s0"
branch_labels = None
depends_on = None


def _tables():
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str):
    return {item["name"] for item in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade():
    if "event_context_reconciliations" not in _tables():
        op.create_table(
            "event_context_reconciliations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("record_kind", sa.String(length=16), nullable=False),
            sa.Column("record_id", sa.Integer(), nullable=False),
            sa.Column("previous_context", sa.JSON(), nullable=False),
            sa.Column("resolved_context", sa.JSON(), nullable=False),
            sa.Column("evidence_type", sa.String(length=32), nullable=False),
            sa.Column("evidence_reference", sa.String(length=255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("reconciled_by_user_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["reconciled_by_user_id"], ["users.id"], ondelete="SET NULL"
            ),
        )

    existing = _indexes("event_context_reconciliations")
    for name, columns in (
        ("ix_event_context_reconciliations_id", ["id"]),
        (
            "ix_event_context_reconciliations_reconciled_by_user_id",
            ["reconciled_by_user_id"],
        ),
        (
            "ix_event_context_reconciliations_source",
            ["record_kind", "record_id", "created_at"],
        ),
    ):
        if name not in existing:
            op.create_index(name, "event_context_reconciliations", columns)


def downgrade():
    # Reconciliation decisions are audit evidence and survive code rollbacks.
    pass
