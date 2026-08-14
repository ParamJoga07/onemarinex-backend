"""Guarantee one open queue item per exact identity conflict.

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "r9s0t1u2v3w4"
down_revision = "q8r9s0t1u2v3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    indexes = {
        row["name"]
        for row in inspect(bind).get_indexes("crew_identity_conflicts")
    }
    if "uq_crew_identity_conflicts_open_identity" in indexes:
        return
    duplicates = bind.execute(sa.text("""
        SELECT coalesce(vessel_id, -1) AS vessel_scope,
               identity_fingerprint,
               count(*)
        FROM crew_identity_conflicts
        WHERE status = 'OPEN'
        GROUP BY coalesce(vessel_id, -1), passport_key, identity_fingerprint
        HAVING count(*) > 1
    """)).fetchall()
    if duplicates:
        raise RuntimeError(
            "Duplicate open identity conflicts require reconciliation: "
            + repr([
                {
                    "vessel_scope": row[0],
                    "identity_fingerprint": row[1],
                    "duplicate_count": row[2],
                }
                for row in duplicates
            ])
            + "; run scripts/preflight_assignment_scoped_operations.py for details"
        )
    op.create_index(
        "uq_crew_identity_conflicts_open_identity",
        "crew_identity_conflicts",
        [sa.text("coalesce(vessel_id, -1)"), "passport_key", "identity_fingerprint"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )


def downgrade():
    # Queue records and their concurrency boundary remain through rollbacks.
    pass
