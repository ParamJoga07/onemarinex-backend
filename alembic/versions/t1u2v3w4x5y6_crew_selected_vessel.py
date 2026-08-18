"""Remember which vessel a crew member selected, before any agent claims them.

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5

Crew can now enter the app before their agent has added them to a manifest, and
the shore leave card has to say which of two very different situations they are
in: waiting on an agent-managed vessel, or aboard a ship no agency runs here.

Only the vessel they picked answers that, and it has to survive a refresh — the
whole point of the PENDING card is that reloading it turns into APPROVED or NOT
ELIGIBLE once the agent uploads the manifest.

The profile already stores a vessel *name*, but a name cannot be trusted for
this: two ships can share one, and the crew list they choose from now spans
every port. The id is unambiguous.

Deliberately nullable and deliberately not a claim of anything. It records a
selection, never an assignment — authorisation continues to come from
crew_assignments alone.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "t1u2v3w4x5y6"
down_revision = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        row["name"]
        for row in inspect(op.get_bind()).get_columns("crew_profiles")
    }
    if "selected_vessel_id" not in columns:
        op.add_column(
            "crew_profiles",
            sa.Column(
                "selected_vessel_id",
                sa.Integer(),
                sa.ForeignKey("vessels.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    indexes = {
        row["name"]
        for row in inspect(op.get_bind()).get_indexes("crew_profiles")
    }
    if "ix_crew_profiles_selected_vessel_id" not in indexes:
        op.create_index(
            "ix_crew_profiles_selected_vessel_id",
            "crew_profiles",
            ["selected_vessel_id"],
        )


def downgrade():
    # A selection is harmless to keep and costly to lose: without it a waiting
    # crew member's card cannot tell PENDING from "no agency here".
    pass
