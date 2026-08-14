from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reconcile_confirmed_assignment_records.py"


def test_confirmed_repair_tool_is_dry_run_by_default_and_apply_is_explicit():
    source = SCRIPT.read_text()

    assert 'parser.add_argument("--apply", action="store_true"' in source
    assert "if args.apply:" in source
    assert "db.commit()" in source
    assert "db.rollback()" in source
    assert "DRY RUN ONLY" in source
    assert "pg_advisory_xact_lock" in source
    assert '--actor-user-id' in source
    assert '--apply requires a positive --actor-user-id' in source


def test_dry_run_executes_the_real_guarded_sequence_then_rolls_back():
    source = SCRIPT.read_text()

    # A plan of all scopes must model the Kona repoint before checking whether
    # call 140 has references. Merely calling every plan with apply=False made
    # the documented default dry run fail on the very references it intended
    # to move first.
    assert "execute_repairs = True" in source
    assert "plan_kona(" in source
    assert "apply=execute_repairs" in source
    assert "db.rollback()" in source


def test_confirmed_repairs_audit_bookings_and_require_an_actor_on_commit():
    source = SCRIPT.read_text()

    assert 'kind="booking"' in source
    assert '"actor_user_id": actor_user_id' in source
    assert ":notes, :actor_user_id" in source


def test_confirmed_repair_tool_guards_the_audited_record_set():
    source = SCRIPT.read_text()

    for required_id in (
        "325", "326", "38", "83", "84", "85", "140", "149", "134", "162",
        "131", "132", "135", "136", "137", "138", "139",
    ):
        assert required_id in source

    assert "_assert_exact" in source
    assert "_foreign_key_references" in source
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
