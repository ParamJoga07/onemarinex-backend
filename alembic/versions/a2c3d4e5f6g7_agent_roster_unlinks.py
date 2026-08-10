"""Allow safe agent roster unlinking and audit it.

Revision ID: a2c3d4e5f6g7
Revises: z1c2d3e4f5g6
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "a2c3d4e5f6g7"
down_revision = "z1c2d3e4f5g6"
branch_labels = None
depends_on = None


def _tables() -> set:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    vessel_columns = {
        c["name"]: c for c in inspect(op.get_bind()).get_columns("vessels")
    }
    if not vessel_columns["agent_id"].get("nullable", True):
        op.alter_column(
            "vessels", "agent_id", existing_type=sa.Integer(), nullable=True
        )
    vessel_fks = inspect(op.get_bind()).get_foreign_keys("vessels")
    agent_fk = next(
        (fk for fk in vessel_fks if fk.get("constrained_columns") == ["agent_id"]),
        None,
    )
    if agent_fk and str((agent_fk.get("options") or {}).get("ondelete", "")).upper() != "SET NULL":
        if not agent_fk.get("name"):
            raise RuntimeError("Cannot safely replace unnamed vessels.agent_id foreign key")
        op.drop_constraint(agent_fk["name"], "vessels", type_="foreignkey")
        op.create_foreign_key(
            "fk_vessels_agent_id", "vessels", "users", ["agent_id"], ["id"],
            ondelete="SET NULL",
        )

    if "agent_roster_events" not in _tables():
        op.create_table(
            "agent_roster_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("vessel_id", sa.Integer(), nullable=True),
            sa.Column("crew_manifest_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("subject_name", sa.String(length=255), nullable=True),
            sa.Column("subject_hpid", sa.String(length=100), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["vessel_id"], ["vessels.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        for column in ("id", "actor_user_id", "vessel_id", "action"):
            op.create_index(
                f"ix_agent_roster_events_{column}",
                "agent_roster_events",
                [column],
            )


def downgrade() -> None:
    if "agent_roster_events" in _tables():
        op.drop_table("agent_roster_events")
    # Do not restore NOT NULL: detached vessels would make that destructive.
