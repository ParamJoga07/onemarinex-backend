"""add SOS timeline and notes

Revision ID: c4e5f6g7h8i9
Revises: b3d4e5f6g7h8
"""

from alembic import op
import sqlalchemy as sa


revision = "c4e5f6g7h8i9"
down_revision = "b3d4e5f6g7h8"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "crew_sos_timeline_events" not in tables:
        op.create_table(
            "crew_sos_timeline_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sos_id", sa.Integer(), sa.ForeignKey("crew_sos_requests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source", sa.String(16), nullable=False, server_default="system"),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("label", sa.String(255), nullable=False),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("actor_name", sa.String(255), nullable=True),
            sa.Column("event_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_crew_sos_timeline_events_sos_id", "crew_sos_timeline_events", ["sos_id"])
    if "crew_sos_notes" not in tables:
        op.create_table(
            "crew_sos_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sos_id", sa.Integer(), sa.ForeignKey("crew_sos_requests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("author_name", sa.String(255), nullable=True),
            sa.Column("note", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_crew_sos_notes_sos_id", "crew_sos_notes", ["sos_id"])


def downgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "crew_sos_notes" in tables:
        op.drop_table("crew_sos_notes")
    if "crew_sos_timeline_events" in tables:
        op.drop_table("crew_sos_timeline_events")
