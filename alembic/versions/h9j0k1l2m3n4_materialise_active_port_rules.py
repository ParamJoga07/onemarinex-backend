"""materialise active port rules from configured return cutoffs

Revision ID: h9j0k1l2m3n4
Revises: g8i9j0k1l2m3
"""

from alembic import op

from app.services.port_identity import reconcile_port_identities


revision = "h9j0k1l2m3n4"
down_revision = "g8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade():
    reconcile_port_identities(op.get_bind())


def downgrade():
    # Derived rules are operational data once edited and are not removed.
    pass
