"""Persist SOS note authorship for safe agent edits.

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "s0t1u2v3w4x5"
down_revision = "r9s0t1u2v3w4"
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        row["name"]
        for row in inspect(op.get_bind()).get_columns("crew_sos_notes")
    }
    if "author_user_id" not in columns:
        op.add_column(
            "crew_sos_notes",
            sa.Column(
                "author_user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    indexes = {
        row["name"]
        for row in inspect(op.get_bind()).get_indexes("crew_sos_notes")
    }
    if "ix_crew_sos_notes_author_user_id" not in indexes:
        op.create_index(
            "ix_crew_sos_notes_author_user_id",
            "crew_sos_notes",
            ["author_user_id"],
        )


def downgrade():
    # Authorship is safety evidence and remains valid across code rollbacks.
    pass
