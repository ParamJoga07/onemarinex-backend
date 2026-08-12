"""Persist immutable operational report snapshots.

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "n5o6p7q8r9s0"
down_revision = "m4n5o6p7q8r9"
branch_labels = None
depends_on = None


def _tables():
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str):
    return {item["name"] for item in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade():
    if "report_snapshots" not in _tables():
        op.create_table(
            "report_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("report_kind", sa.String(length=32), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=True),
            sa.Column("source_reference", sa.String(length=255), nullable=False),
            sa.Column("agency_id", sa.Integer(), nullable=True),
            sa.Column("vessel_call_id", sa.Integer(), nullable=True),
            sa.Column("generated_by_user_id", sa.Integer(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("payload_sha256", sa.String(length=64), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["agency_id"], ["agent_profiles.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["vessel_call_id"], ["vessel_calls.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["generated_by_user_id"], ["users.id"], ondelete="SET NULL"
            ),
        )

    existing = _indexes("report_snapshots")
    for name, columns in (
        ("ix_report_snapshots_id", ["id"]),
        ("ix_report_snapshots_agency_id", ["agency_id"]),
        ("ix_report_snapshots_vessel_call_id", ["vessel_call_id"]),
        ("ix_report_snapshots_generated_by_user_id", ["generated_by_user_id"]),
        ("ix_report_snapshots_source", ["report_kind", "source_id"]),
        ("ix_report_snapshots_agency_created", ["agency_id", "created_at"]),
    ):
        if name not in existing:
            op.create_index(name, "report_snapshots", columns)


def downgrade():
    # Report artifacts are audit records. Deployments may roll application code
    # back while retaining this additive table, but must not erase artifacts.
    pass
