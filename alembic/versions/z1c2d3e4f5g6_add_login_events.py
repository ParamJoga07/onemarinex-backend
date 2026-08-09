"""Record successful logins.

Nothing tracked logins before this — no last_login column, no audit table — so
the superadmin "how many logins" question had no data behind it at all.
Registrations can be counted retroactively from users.created_at; logins cannot,
and necessarily start from this migration.

Revision ID: z1c2d3e4f5g6
Revises: y1c2d3e4f5g6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "z1c2d3e4f5g6"
down_revision = "y1c2d3e4f5g6"
branch_labels = None
depends_on = None


def _tables() -> set:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    # create_all() runs at app startup and will have made this table already if
    # the web process booted before this migration ran — which is the normal
    # ordering on a platform with no pre-deploy hook. Guarding keeps the
    # migration usable either way, matching the Crew Safety Center revision.
    if "login_events" in _tables():
        return

    op.create_table(
        "login_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("driver_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_events_id", "login_events", ["id"])
    op.create_index("ix_login_events_user_id", "login_events", ["user_id"])
    op.create_index("ix_login_events_driver_id", "login_events", ["driver_id"])
    op.create_index("ix_login_events_role", "login_events", ["role"])
    # The screen filters by date range, so this index carries the query.
    op.create_index("ix_login_events_created_at", "login_events", ["created_at"])


def downgrade() -> None:
    if "login_events" not in _tables():
        return

    op.drop_index("ix_login_events_created_at", table_name="login_events")
    op.drop_index("ix_login_events_role", table_name="login_events")
    op.drop_index("ix_login_events_driver_id", table_name="login_events")
    op.drop_index("ix_login_events_user_id", table_name="login_events")
    op.drop_index("ix_login_events_id", table_name="login_events")
    op.drop_table("login_events")
