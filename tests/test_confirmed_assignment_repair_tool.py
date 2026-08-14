from pathlib import Path
from unittest.mock import Mock

from scripts import reconcile_confirmed_assignment_records as repair


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile_confirmed_assignment_records.py"


def test_confirmed_repair_tool_requires_one_scope_and_apply_is_explicit():
    source = SCRIPT.read_text()

    assert '"--scope", required=True' in source
    assert 'action="append"' not in source
    assert 'parser.add_argument("--apply", action="store_true"' in source
    assert "if args.apply:" in source
    assert "db.commit()" in source
    assert "db.rollback()" in source
    assert "DRY RUN ONLY" in source
    assert "pg_advisory_xact_lock" in source
    assert '--actor-user-id' in source
    assert '--apply requires a positive --actor-user-id' in source


def test_dry_run_never_executes_repairs():
    source = SCRIPT.read_text()

    assert "execute_repairs" not in source
    assert "apply=args.apply" in source
    assert "db.rollback()" in source


def test_confirmed_repairs_audit_bookings_and_require_an_actor_on_commit():
    source = SCRIPT.read_text()

    assert 'kind="booking"' in source
    assert '"actor_user_id": actor_user_id' in source
    assert ":notes, :actor_user_id" in source
    assert "_assert_superadmin_actor" in source
    assert 'role != "superadmin"' in source
    assert "PROD-AUDIT-2026-08-12-COMMON-LUCK-140" in source
    assert "PROD-AUDIT-2026-08-12-SERENITY-EMPTY-CALLS" in source


def test_kona_repair_keeps_snapshot_labels_with_corrected_ids():
    source = SCRIPT.read_text()

    assert '"booking": ("port",)' in source
    assert '"sos": ("port_name", "vessel")' in source
    assert '"incident": ("port_name",)' in source
    assert "port=:port_name" in source
    assert "port_name=:port_name" in source


def test_serenity_dry_run_checks_reconciliation_references(monkeypatch):
    calls = {
        call_id: {"id": call_id, "vessel_id": 120, "agency_id": 6}
        for call_id in repair.SERENITY_EMPTY_CALL_IDS
    }
    assignments = [
        {"id": call_id * 100 + offset, "vessel_call_id": call_id}
        for call_id in repair.SERENITY_EMPTY_CALL_IDS
        for offset in range(24)
    ]
    keep_result = Mock()
    keep_result.one.return_value = {"id": 131, "vessel_id": 120, "agency_id": 6}
    assignment_result = Mock()
    assignment_result.mappings.return_value.all.return_value = assignments
    db = Mock()
    db.execute.side_effect = [keep_result, assignment_result]
    monkeypatch.setattr(repair, "_load_exact_rows", lambda *_args, **_kwargs: calls)
    monkeypatch.setattr(repair, "_foreign_key_references", lambda *_args, **_kwargs: [])
    reconciliation_check = Mock(return_value=[])
    monkeypatch.setattr(repair, "_resolved_reconciliation_references", reconciliation_check)

    repair.plan_serenity_duplicates(db, apply=False)

    reconciliation_check.assert_called_once_with(db, repair.SERENITY_EMPTY_CALL_IDS)


def test_confirmed_repair_tool_guards_the_audited_record_set():
    source = SCRIPT.read_text()

    for required_id in (
        "325", "326", "38", "83", "84", "85", "140", "149", "134", "162",
        "131", "132", "135", "136", "137", "138", "139",
    ):
        assert required_id in source

    assert "_assert_exact" in source
    assert source.count("FOR UPDATE") >= 5
    assert "_foreign_key_references" in source
    assert "_resolved_reconciliation_references" in source
    assert "PROD-AUDIT-2026-08-12-KONA" in source


def test_confirmed_repair_tool_does_not_guess_ambiguous_records():
    source = SCRIPT.read_text()

    # These records need external evidence and must never be automatic targets.
    assert "SOS 30" not in source
    assert "SOS 31" not in source
    assert "SOS 32" not in source
    assert "SOS 33" not in source
    assert "SOS 34" not in source
    assert "SOS 35" not in source
    assert "SOS 37" not in source
    assert "booking 323" not in source
    assert "booking 324" not in source
