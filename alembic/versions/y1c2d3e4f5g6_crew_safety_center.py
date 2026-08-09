"""Crew Safety Center: incident vessel link, taxonomy, timeline

The incidents table could not support the Crew Safety Center design:

  * no link to a vessel — the only route to a ship was the reporter's HPID,
    which fails for crew without a registered account
  * no category or sub-category, so the crew's category dropdown was dropped
    silently by the API and nothing was ever recorded
  * no severity, no resolved-at, no cancelled-at
  * no CANCELLED status, though the detail screen offers "Cancel Incident"
  * no timeline table — incident_notes cannot express system vs agent events

Additive only. Nothing is dropped and no existing row changes meaning.

Revision ID: y1c2d3e4f5g6
Revises: x1c2d3e4f5g6
Create Date: 2026-08-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "y1c2d3e4f5g6"
down_revision = "x1c2d3e4f5g6"
branch_labels = None
depends_on = None


def _columns(table: str) -> set:
    return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}


def _tables() -> set:
    return set(inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _columns("incidents")

    if "vessel_id" not in existing:
        op.add_column("incidents", sa.Column("vessel_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_incidents_vessel_id", "incidents", "vessels",
            ["vessel_id"], ["id"], ondelete="SET NULL",
        )
        op.create_index("ix_incidents_vessel_id", "incidents", ["vessel_id"])

    for name, column in [
        ("category", sa.Column("category", sa.String(length=64), nullable=True)),
        ("sub_category", sa.Column("sub_category", sa.String(length=64), nullable=True)),
        ("severity", sa.Column("severity", sa.String(length=16), nullable=True)),
        ("resolved_at", sa.Column("resolved_at", sa.DateTime(), nullable=True)),
        ("cancelled_at", sa.Column("cancelled_at", sa.DateTime(), nullable=True)),
    ]:
        if name not in existing:
            op.add_column("incidents", column)

    if "category" not in existing:
        op.create_index("ix_incidents_category", "incidents", ["category"])

    # status is a Postgres enum type, so a new label has to be added to the type
    # itself. Postgres 12+ allows this inside a transaction provided the new
    # value is not used in the same transaction — it is not.
    op.execute("ALTER TYPE incidentstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")

    if "incident_timeline_events" not in _tables():
        op.create_table(
            "incident_timeline_events",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("incident_id", sa.Integer(),
                      sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source", sa.String(length=16), nullable=False, server_default="system"),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("actor_name", sa.String(length=255), nullable=True),
            sa.Column("event_time", sa.DateTime(), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_incident_timeline_incident_id",
                        "incident_timeline_events", ["incident_id"])


def downgrade() -> None:
    if "incident_timeline_events" in _tables():
        op.drop_table("incident_timeline_events")

    existing = _columns("incidents")
    for name in ("cancelled_at", "resolved_at", "severity", "sub_category", "category"):
        if name in existing:
            op.drop_column("incidents", name)
    if "vessel_id" in existing:
        op.drop_constraint("fk_incidents_vessel_id", "incidents", type_="foreignkey")
        op.drop_column("incidents", "vessel_id")

    # The CANCELLED enum label is deliberately left in place: Postgres cannot
    # remove a value from an enum type without recreating it, and any row using
    # it would break. Leaving an unused label is harmless.
