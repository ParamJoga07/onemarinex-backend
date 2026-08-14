"""Schema and deployment guards for assignment-scoped operations."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "alembic/versions/r9s0t1u2v3w4_assignment_scoped_operations.py"
)
PREFLIGHT = ROOT / "scripts/preflight_assignment_scoped_operations.py"


def test_assignment_scoped_release_stays_on_the_single_linear_graph():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["r9s0t1u2v3w4"]
    assert (
        script.get_revision("r9s0t1u2v3w4").down_revision
        == "o6p7q8r9s0t1"
    )


def test_assignment_scoped_migration_blocks_duplicates_before_constraints():
    source = MIGRATION.read_text()
    duplicate_guard = source.index("if blocked:")

    assert source.index('"active crew profiles"') < duplicate_guard
    assert source.index('"pending passports"') < duplicate_guard
    assert source.index('"driver magic links"') < duplicate_guard
    assert source.index("uq_cab_bookings_crew_idempotency_key") > duplicate_guard
    assert source.index("uq_crew_assignments_active_profile") > duplicate_guard
    assert (
        source.index("uq_crew_assignments_active_pending_passport")
        > duplicate_guard
    )
    assert source.index("uq_driver_magic_links_booking_id") > duplicate_guard


def test_assignment_snapshot_backfill_precedes_unique_indexes():
    source = MIGRATION.read_text()
    first_unique_index = source.index(
        "uq_cab_bookings_crew_idempotency_key"
    )

    assert source.index("SET shore_pass_eligible") < first_unique_index
    assert source.index("SET emergency_email = profile.sos_email") < first_unique_index
    assert '"crew_assignment_id"' in source
    assert '"vessel_call_id"' in source
    assert "candidates.candidate_count = 1" in source
    assert "server_default=sa.false()" in source


def test_preflight_supports_only_the_previous_and_new_heads_and_is_read_only():
    source = PREFLIGHT.read_text()

    assert 'EXPECTED_HEAD = "r9s0t1u2v3w4"' in source
    assert 'PREVIOUS_HEADS = {"o6p7q8r9s0t1"}' in source
    assert "duplicate_active_profiles" in source
    assert "duplicate_pending_passports" in source
    assert "duplicate_magic_links" in source
    assert "duplicate_booking_idempotency_keys" in source
    assert "invalid_open_calls" in source
    assert "assignment_event_mismatches" in source
    assert "sos_snapshot_context_mismatches" in source
    assert "unresolved_agent_visible_events" in source
    assert "duplicate_equivalent_empty_calls" in source
    assert "duplicate_open_identity_conflicts" in source
    assert "invalid_identity_conflict_states" in source
    assert "resolved_identity_conflicts_without_audit" in source
    assert "identity conflict queue tables are missing" in source
    assert "identity conflict queue columns are missing" in source
    assert "ix_crew_identity_conflicts_queue" in source
    assert "ix_crew_identity_conflicts_identity" in source
    assert "ix_crew_identity_conflict_audits_conflict_id" in source
    assert "jsonb_build_array(conflict.selected_profile_id)" in source
    assert "shore pass assignment context is missing" in source
    assert "ix_shore_passes_crew_assignment_id" in source
    assert "ix_shore_passes_vessel_call_id" in source
    assert "booking.crew_assignment_id IS DISTINCT FROM sos.crew_assignment_id" in source
    assert "lower(trim(sos.vessel)) <> lower(trim(call.vessel_name))" in source
    assert "NOT EXISTS" in source
    assert not any(
        token in source.upper()
        for token in ("UPDATE ", "DELETE ", "INSERT ", "ALTER ", "DROP ")
    )


def test_identity_queue_is_created_in_its_final_shape():
    source = MIGRATION.read_text()

    assert 'sa.Column("identity_fingerprint", sa.String(64), nullable=False)' in source
    assert "uq_crew_identity_conflicts_open_identity" in source
    assert '"open identity conflicts"' in source
