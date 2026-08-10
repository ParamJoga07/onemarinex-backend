"""add explicit notification audiences

Revision ID: b3d4e5f6g7h8
Revises: a2c3d4e5f6g7
"""

from alembic import op
import sqlalchemy as sa


revision = "b3d4e5f6g7h8"
down_revision = "a2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("notifications")}
    if "audience_type" not in columns:
        op.add_column("notifications", sa.Column("audience_type", sa.String(32), nullable=True))
    if "target_vessel_ids" not in columns:
        op.add_column("notifications", sa.Column("target_vessel_ids", sa.JSON(), nullable=True))
    indexes = {item["name"] for item in inspector.get_indexes("notifications")}
    if "ix_notifications_audience_type" not in indexes:
        op.create_index(
            "ix_notifications_audience_type", "notifications", ["audience_type"], unique=False
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("notifications")}
    if "ix_notifications_audience_type" in indexes:
        op.drop_index("ix_notifications_audience_type", table_name="notifications")
    columns = {item["name"] for item in inspector.get_columns("notifications")}
    if "target_vessel_ids" in columns:
        op.drop_column("notifications", "target_vessel_ids")
    if "audience_type" in columns:
        op.drop_column("notifications", "audience_type")
