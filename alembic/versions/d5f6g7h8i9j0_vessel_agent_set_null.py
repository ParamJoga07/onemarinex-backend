"""make vessel-agent deletion preserve canonical vessels

Revision ID: d5f6g7h8i9j0
Revises: c4e5f6g7h8i9
"""

from alembic import op
import sqlalchemy as sa


revision = "d5f6g7h8i9j0"
down_revision = "c4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    fk = next(
        (item for item in inspector.get_foreign_keys("vessels") if item.get("constrained_columns") == ["agent_id"]),
        None,
    )
    if fk and str((fk.get("options") or {}).get("ondelete", "")).upper() == "SET NULL":
        return
    if fk:
        if not fk.get("name"):
            raise RuntimeError("Cannot safely replace unnamed vessels.agent_id foreign key")
        op.drop_constraint(fk["name"], "vessels", type_="foreignkey")
    op.create_foreign_key(
        "fk_vessels_agent_id", "vessels", "users", ["agent_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    # Do not restore CASCADE. A rollback must not make deleting an agent capable
    # of deleting canonical vessel/history records.
    pass
