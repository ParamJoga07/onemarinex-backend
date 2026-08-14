"""Scope identity decisions to the exact proposed person.

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
"""

from alembic import op
import hashlib
import json
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "q8r9s0t1u2v3"
down_revision = "p7q8r9s0t1u2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "crew_identity_conflicts" not in tables:
        op.create_table(
            "crew_identity_conflicts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("operation", sa.String(32), nullable=False),
            sa.Column("vessel_id", sa.Integer(), nullable=True),
            sa.Column("passport_key", sa.String(128), nullable=False),
            sa.Column("identity_fingerprint", sa.String(64), nullable=False),
            sa.Column("proposed_identity", sa.JSON(), nullable=False),
            sa.Column("candidate_profile_ids", sa.JSON(), nullable=False),
            sa.Column("conflict_message", sa.Text(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("resolution_action", sa.String(32), nullable=True),
            sa.Column("selected_profile_id", sa.Integer(), nullable=True),
            sa.Column("evidence_type", sa.String(64), nullable=True),
            sa.Column("evidence_reference", sa.String(255), nullable=True),
            sa.Column("resolution_reason", sa.Text(), nullable=True),
            sa.Column("resolved_by_user_id", sa.Integer(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["vessel_id"], ["vessels.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["selected_profile_id"], ["crew_profiles.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        tables.add("crew_identity_conflicts")
        inspector = inspect(bind)

    columns = {row["name"] for row in inspector.get_columns("crew_identity_conflicts")}
    if "identity_fingerprint" not in columns:
        op.add_column(
            "crew_identity_conflicts",
            sa.Column("identity_fingerprint", sa.String(64), nullable=True),
        )

    # No resolution created before this field existed is safe to reuse: its
    # proposed identity was not bound to the decision. Fingerprint all rows for
    # audit/search, but reopen resolved legacy rows so a human must confirm the
    # exact proposal once under the new versioned contract.
    rows = bind.execute(sa.text(
        "SELECT id, proposed_identity, status FROM crew_identity_conflicts "
        "WHERE identity_fingerprint IS NULL"
    )).mappings().all()
    if rows:
        for row in rows:
            proposed = row["proposed_identity"] or {}
            if isinstance(proposed, (str, bytes)):
                try:
                    proposed = json.loads(proposed)
                except (ValueError, TypeError):
                    proposed = {}
            if not isinstance(proposed, dict):
                proposed = {}
            normalized = {
                "name": " ".join(str(proposed.get("name") or "").strip().casefold().split()),
                "nationality": str(proposed.get("nationality") or "").strip().upper() or None,
                "passport_number": "".join(
                    str(proposed.get("passport_number") or "").strip().upper().split()
                ) or None,
            }
            values = {
                "fingerprint": hashlib.sha256(
                    json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "id": row["id"],
            }
            bind.execute(sa.text(
                "UPDATE crew_identity_conflicts "
                "SET identity_fingerprint = :fingerprint, "
                "status = CASE WHEN status = 'RESOLVED' THEN 'OPEN' ELSE status END, "
                "resolution_action = CASE WHEN status = 'RESOLVED' THEN NULL ELSE resolution_action END, "
                "selected_profile_id = CASE WHEN status = 'RESOLVED' THEN NULL ELSE selected_profile_id END, "
                "evidence_type = CASE WHEN status = 'RESOLVED' THEN NULL ELSE evidence_type END, "
                "evidence_reference = CASE WHEN status = 'RESOLVED' THEN NULL ELSE evidence_reference END, "
                "resolution_reason = CASE WHEN status = 'RESOLVED' THEN NULL ELSE resolution_reason END, "
                "resolved_by_user_id = CASE WHEN status = 'RESOLVED' THEN NULL ELSE resolved_by_user_id END, "
                "resolved_at = CASE WHEN status = 'RESOLVED' THEN NULL ELSE resolved_at END, "
                "version = CASE WHEN status = 'RESOLVED' THEN version + 1 ELSE version END "
                "WHERE id = :id"
            ), values)

    op.alter_column(
        "crew_identity_conflicts",
        "identity_fingerprint",
        existing_type=sa.String(64),
        nullable=False,
    )
    indexes = {row["name"] for row in inspect(bind).get_indexes("crew_identity_conflicts")}
    if "ix_crew_identity_conflicts_identity_fingerprint" not in indexes:
        op.create_index(
            "ix_crew_identity_conflicts_identity_fingerprint",
            "crew_identity_conflicts",
            ["identity_fingerprint"],
        )
    for name, columns in (
        ("ix_crew_identity_conflicts_id", ["id"]),
        ("ix_crew_identity_conflicts_vessel_id", ["vessel_id"]),
        ("ix_crew_identity_conflicts_passport_key", ["passport_key"]),
        ("ix_crew_identity_conflicts_selected_profile_id", ["selected_profile_id"]),
        ("ix_crew_identity_conflicts_resolved_by_user_id", ["resolved_by_user_id"]),
        ("ix_crew_identity_conflicts_queue", ["status", "created_at"]),
        ("ix_crew_identity_conflicts_identity", ["vessel_id", "passport_key", "created_at"]),
    ):
        if name not in indexes:
            op.create_index(name, "crew_identity_conflicts", columns)

    if "crew_identity_conflict_audits" not in tables:
        op.create_table(
            "crew_identity_conflict_audits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("conflict_id", sa.Integer(), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(32), nullable=False),
            sa.Column("expected_version", sa.Integer(), nullable=False),
            sa.Column("before_state", sa.JSON(), nullable=False),
            sa.Column("after_state", sa.JSON(), nullable=False),
            sa.Column("evidence_type", sa.String(64), nullable=False),
            sa.Column("evidence_reference", sa.String(255), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["conflict_id"], ["crew_identity_conflicts.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        )
    audit_indexes = {
        row["name"] for row in inspect(bind).get_indexes("crew_identity_conflict_audits")
    }
    for name, columns in (
        ("ix_crew_identity_conflict_audits_id", ["id"]),
        ("ix_crew_identity_conflict_audits_conflict_id", ["conflict_id"]),
        ("ix_crew_identity_conflict_audits_actor_user_id", ["actor_user_id"]),
    ):
        if name not in audit_indexes:
            op.create_index(name, "crew_identity_conflict_audits", columns)


def downgrade():
    # Decisions and their evidence remain durable during a code rollback.
    pass
