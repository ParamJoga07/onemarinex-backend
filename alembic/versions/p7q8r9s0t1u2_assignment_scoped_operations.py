"""Assignment-scoped operations and request idempotency.

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "p7q8r9s0t1u2"
down_revision = "o6p7q8r9s0t1"
branch_labels = None
depends_on = None


def _columns(table):
    return {row["name"] for row in inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {row["name"] for row in inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
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
    tables = set(inspect(bind).get_table_names())
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
    for table, indexes in (
        ("crew_identity_conflicts", (
            ("ix_crew_identity_conflicts_id", ["id"]),
            ("ix_crew_identity_conflicts_vessel_id", ["vessel_id"]),
            ("ix_crew_identity_conflicts_passport_key", ["passport_key"]),
            ("ix_crew_identity_conflicts_identity_fingerprint", ["identity_fingerprint"]),
            ("ix_crew_identity_conflicts_selected_profile_id", ["selected_profile_id"]),
            ("ix_crew_identity_conflicts_resolved_by_user_id", ["resolved_by_user_id"]),
            ("ix_crew_identity_conflicts_queue", ["status", "created_at"]),
            ("ix_crew_identity_conflicts_identity", ["vessel_id", "passport_key", "created_at"]),
        )),
        ("crew_identity_conflict_audits", (
            ("ix_crew_identity_conflict_audits_id", ["id"]),
            ("ix_crew_identity_conflict_audits_conflict_id", ["conflict_id"]),
            ("ix_crew_identity_conflict_audits_actor_user_id", ["actor_user_id"]),
        )),
    ):
        existing = _indexes(table)
        for name, columns in indexes:
            if name not in existing:
                op.create_index(name, table, columns)

    columns = _columns("cab_bookings")
    if "client_idempotency_key" not in columns:
        op.add_column(
            "cab_bookings",
            sa.Column("client_idempotency_key", sa.String(64), nullable=True),
        )
    if "request_fingerprint" not in columns:
        op.add_column(
            "cab_bookings",
            sa.Column("request_fingerprint", sa.String(64), nullable=True),
        )

    columns = _columns("crew_assignments")
    if "emergency_email" not in columns:
        op.add_column(
            "crew_assignments",
            sa.Column("emergency_email", sa.String(255), nullable=True),
        )
    added_shore_pass_eligible = "shore_pass_eligible" not in columns
    if added_shore_pass_eligible:
        op.add_column(
            "crew_assignments",
            sa.Column(
                "shore_pass_eligible",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if added_shore_pass_eligible:
        bind.execute(sa.text("""
            UPDATE crew_assignments AS assignment
            SET shore_pass_eligible = COALESCE(manifest.shore_pass_eligible, false)
            FROM vessel_crew AS manifest
            WHERE assignment.vessel_crew_id = manifest.id
        """))

    columns = _columns("shore_passes")
    if "crew_assignment_id" not in columns:
        op.add_column(
            "shore_passes",
            sa.Column(
                "crew_assignment_id",
                sa.Integer(),
                sa.ForeignKey("crew_assignments.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "vessel_call_id" not in columns:
        op.add_column(
            "shore_passes",
            sa.Column(
                "vessel_call_id",
                sa.Integer(),
                sa.ForeignKey("vessel_calls.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    # Backfill only when the historical evidence identifies one assignment.
    # Multiple calls for the same crew/vessel remain unresolved rather than
    # being attached to whichever call happens to sort first.
    bind.execute(sa.text("""
        WITH candidates AS (
          SELECT shore_pass.id AS shore_pass_id,
                 min(assignment.id) AS assignment_id,
                 min(assignment.vessel_call_id) AS vessel_call_id,
                 count(*) AS candidate_count
          FROM shore_passes AS shore_pass
          JOIN crew_assignments AS assignment
            ON assignment.crew_profile_id = shore_pass.crew_profile_id
          JOIN vessel_calls AS call ON call.id = assignment.vessel_call_id
          WHERE lower(trim(call.vessel_name)) = lower(trim(shore_pass.vessel_name))
          GROUP BY shore_pass.id
        )
        UPDATE shore_passes AS shore_pass
        SET crew_assignment_id = candidates.assignment_id,
            vessel_call_id = candidates.vessel_call_id
        FROM candidates
        WHERE candidates.shore_pass_id = shore_pass.id
          AND candidates.candidate_count = 1
          AND shore_pass.crew_assignment_id IS NULL
    """))
    # Initial per-assignment snapshot preserves configured recipients through
    # the backend-first rollout. Future edits are assignment-specific.
    bind.execute(sa.text("""
        UPDATE crew_assignments AS assignment
        SET emergency_email = profile.sos_email
        FROM crew_profiles AS profile
        WHERE assignment.crew_profile_id = profile.id
          AND assignment.emergency_email IS NULL
          AND profile.sos_email IS NOT NULL
          AND trim(profile.sos_email) <> ''
    """))

    duplicate_booking_keys = bind.execute(sa.text("""
        SELECT crew_id, client_idempotency_key, count(*)
        FROM cab_bookings
        WHERE client_idempotency_key IS NOT NULL
        GROUP BY crew_id, client_idempotency_key
        HAVING count(*) > 1
    """)).fetchall()
    duplicate_profiles = bind.execute(sa.text("""
        SELECT vessel_call_id, crew_profile_id, count(*)
        FROM crew_assignments
        WHERE ended_at IS NULL AND crew_profile_id IS NOT NULL
        GROUP BY vessel_call_id, crew_profile_id
        HAVING count(*) > 1
    """)).fetchall()
    duplicate_passports = bind.execute(sa.text("""
        SELECT vessel_call_id,
               upper(replace(trim(passport_number), ' ', '')) AS passport_key,
               count(*)
        FROM crew_assignments
        WHERE ended_at IS NULL AND crew_profile_id IS NULL
          AND passport_number IS NOT NULL AND trim(passport_number) <> ''
        GROUP BY vessel_call_id,
                 upper(replace(trim(passport_number), ' ', ''))
        HAVING count(*) > 1
    """)).fetchall()
    duplicate_links = bind.execute(sa.text("""
        SELECT booking_id, count(*)
        FROM driver_magic_links
        GROUP BY booking_id
        HAVING count(*) > 1
    """)).fetchall()
    problems = {
        "booking idempotency keys": duplicate_booking_keys,
        "active crew profiles": duplicate_profiles,
        "pending passports": duplicate_passports,
        "driver magic links": duplicate_links,
    }
    blocked = {key: value for key, value in problems.items() if value}
    if blocked:
        raise RuntimeError(
            "Release preflight found duplicates; reconcile before migration: "
            + repr({key: len(rows) for key, rows in blocked.items()})
            + "; run scripts/preflight_assignment_scoped_operations.py for details"
        )

    indexes = _indexes("cab_bookings")
    if "ix_cab_bookings_client_idempotency_key" not in indexes:
        op.create_index(
            "ix_cab_bookings_client_idempotency_key",
            "cab_bookings",
            ["client_idempotency_key"],
        )
    if "uq_cab_bookings_crew_idempotency_key" not in indexes:
        op.create_index(
            "uq_cab_bookings_crew_idempotency_key",
            "cab_bookings",
            ["crew_id", "client_idempotency_key"],
            unique=True,
            postgresql_where=sa.text("client_idempotency_key IS NOT NULL"),
        )

    indexes = _indexes("crew_assignments")
    if "uq_crew_assignments_active_profile" not in indexes:
        op.create_index(
            "uq_crew_assignments_active_profile",
            "crew_assignments",
            ["vessel_call_id", "crew_profile_id"],
            unique=True,
            postgresql_where=sa.text(
                "ended_at IS NULL AND crew_profile_id IS NOT NULL"
            ),
        )
    if "uq_crew_assignments_active_pending_passport" not in indexes:
        op.execute(sa.text("""
            CREATE UNIQUE INDEX uq_crew_assignments_active_pending_passport
            ON crew_assignments (
                vessel_call_id,
                upper(replace(trim(passport_number), ' ', ''))
            )
            WHERE ended_at IS NULL AND crew_profile_id IS NULL
              AND passport_number IS NOT NULL AND trim(passport_number) <> ''
        """))

    indexes = _indexes("driver_magic_links")
    if "uq_driver_magic_links_booking_id" not in indexes:
        op.create_index(
            "uq_driver_magic_links_booking_id",
            "driver_magic_links",
            ["booking_id"],
            unique=True,
        )
    indexes = _indexes("shore_passes")
    if "ix_shore_passes_crew_assignment_id" not in indexes:
        op.create_index(
            "ix_shore_passes_crew_assignment_id",
            "shore_passes",
            ["crew_assignment_id"],
        )
    if "ix_shore_passes_vessel_call_id" not in indexes:
        op.create_index(
            "ix_shore_passes_vessel_call_id",
            "shore_passes",
            ["vessel_call_id"],
        )


def downgrade():
    # Assignment ownership and idempotency history are safety evidence; do not
    # remove them automatically during a code rollback.
    pass
