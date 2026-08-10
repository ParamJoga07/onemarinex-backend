"""repoint canonical port dependents and initialise active rules

Revision ID: g8i9j0k1l2m3
Revises: f7h8i9j0k1l2
"""

from alembic import op

from app.services.port_identity import reconcile_port_identities


revision = "g8i9j0k1l2m3"
down_revision = "f7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade():
    # Alembic wraps this in one transaction on PostgreSQL. Codes, dependent
    # references, rule merges and active-port row creation therefore move as a
    # single unit or not at all.
    reconcile_port_identities(op.get_bind())


def downgrade():
    # This migration repairs ambiguous legacy strings and removes true orphan
    # rule rows. Their original spellings cannot be reconstructed reliably.
    pass
