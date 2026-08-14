#!/usr/bin/env python3
"""Plan or apply the production repairs supported by confirmed evidence.

This script deliberately does not attempt to resolve ambiguous records.  Its
targets and expected current values come from the read-only 12 August 2026
production audit.  Every target is compared with that expected state before a
write can occur, so rerunning the script after another repair fails closed.

Dry run (default)::

    PYTHONPATH=. python scripts/reconcile_confirmed_assignment_records.py

Apply the confirmed Kona repair only::

    PYTHONPATH=. python scripts/reconcile_confirmed_assignment_records.py \
        --scope kona --actor-user-id <SUPERADMIN_USER_ID> --apply

Retire invalid Common Luck call 140 after the Kona repair::

    PYTHONPATH=. python scripts/reconcile_confirmed_assignment_records.py \
        --scope common-luck-140 --actor-user-id <SUPERADMIN_USER_ID> --apply

Remove the six empty duplicate Serenity calls after the lifecycle fix::

    PYTHONPATH=. python scripts/reconcile_confirmed_assignment_records.py \
        --scope serenity-empty-calls --actor-user-id <SUPERADMIN_USER_ID> --apply

The three scopes may be selected together. They execute in one transaction.
No Jim Ming, ambiguous booking, duplicate-identity, or ambiguous SOS record is
changed by this tool.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402


KONA_CONTEXT = {
    "vessel_id": 149,
    "vessel_call_id": 134,
    "agency_id": 5,
    "crew_assignment_id": 162,
}
INVALID_COMMON_LUCK_CALL_ID = 140
SERENITY_KEEP_CALL_ID = 131
SERENITY_EMPTY_CALL_IDS = (132, 135, 136, 137, 138, 139)

EXPECTED_BOOKINGS = {
    325: {"booking_id": "CAB-5C562625", "vessel_id": 71, "vessel_call_id": 140,
          "agency_id": None, "crew_assignment_id": None, "crew_id": 8},
    326: {"booking_id": "CAB-5A007A12", "vessel_id": 71, "vessel_call_id": 140,
          "agency_id": None, "crew_assignment_id": None, "crew_id": 8},
}
EXPECTED_SOS = {
    38: {"trip_id": "CAB-5A007A12", "vessel_id": 71, "vessel_call_id": 140,
         "agency_id": None, "crew_assignment_id": None, "crew_profile_id": 8},
}
EXPECTED_INCIDENTS = {
    83: {"trip_id": "CAB-5A007A12", "vessel_id": 71, "vessel_call_id": 140,
         "agency_id": None, "crew_assignment_id": None, "crew_profile_id": 8},
    84: {"trip_id": "CAB-5A007A12", "vessel_id": 71, "vessel_call_id": 140,
         "agency_id": None, "crew_assignment_id": None, "crew_profile_id": 8},
    85: {"trip_id": "CAB-5A007A12", "vessel_id": 71, "vessel_call_id": 140,
         "agency_id": None, "crew_assignment_id": None, "crew_profile_id": 8},
}


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping if hasattr(row, "_mapping") else row)


def _assert_exact(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    differences = {
        key: {"expected": expected_value, "actual": actual.get(key)}
        for key, expected_value in expected.items()
        if actual.get(key) != expected_value
    }
    if differences:
        raise RuntimeError(f"{label} changed since the audited snapshot: {differences}")


def _load_exact_rows(db, table: str, ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    ids = tuple(ids)
    rows = db.execute(
        text(f"SELECT * FROM {table} WHERE id = ANY(:ids) ORDER BY id"),
        {"ids": list(ids)},
    ).mappings().all()
    result = {row["id"]: dict(row) for row in rows}
    if set(result) != set(ids):
        raise RuntimeError(
            f"Expected {table} IDs {sorted(ids)}, found {sorted(result)}"
        )
    return result


def _audit_record(
    db,
    *,
    kind: str,
    record_id: int,
    previous: dict,
    resolved: dict,
    actor_user_id: int | None,
) -> None:
    existing = db.execute(text("""
        SELECT count(*)
        FROM event_context_reconciliations
        WHERE record_kind = :kind
          AND record_id = :record_id
          AND evidence_reference = 'PROD-AUDIT-2026-08-12-KONA'
    """), {"kind": kind, "record_id": record_id}).scalar_one()
    if existing:
        raise RuntimeError(f"Audit already exists for {kind} {record_id}")
    db.execute(text("""
        INSERT INTO event_context_reconciliations (
            record_kind, record_id, previous_context, resolved_context,
            evidence_type, evidence_reference, notes, reconciled_by_user_id
        ) VALUES (
            :kind, :record_id, CAST(:previous AS JSON), CAST(:resolved AS JSON),
            'trip_record', 'PROD-AUDIT-2026-08-12-KONA',
            :notes, :actor_user_id
        )
    """), {
        "kind": kind,
        "record_id": record_id,
        "previous": json.dumps(previous, default=str),
        "resolved": json.dumps(resolved, default=str),
        "actor_user_id": actor_user_id,
        "notes": (
            "Read-only production audit confirmed that the linked booking was "
            "created after assignment 162 became active on MV KONA EXPLORER; "
            "the previous Common Luck call was created after archive."
        ),
    })


def plan_kona(db, *, apply: bool, actor_user_id: int | None = None) -> None:
    call = _row_dict(db.execute(text("""
        SELECT id, vessel_id, agency_id, port_id, vessel_name, ended_at
        FROM vessel_calls WHERE id = 134
    """)).one())
    _assert_exact(call, {
        "id": 134,
        "vessel_id": 149,
        "agency_id": 5,
        "vessel_name": "MV KONA EXPLORER",
        "ended_at": None,
    }, "Kona call 134")
    if call["port_id"] is None:
        raise RuntimeError("Kona call 134 has no port_id")

    assignment = _row_dict(db.execute(text("""
        SELECT id, vessel_call_id, crew_profile_id, ended_at
        FROM crew_assignments WHERE id = 162
    """)).one())
    _assert_exact(assignment, {
        "id": 162,
        "vessel_call_id": 134,
        "crew_profile_id": 8,
        "ended_at": None,
    }, "Kona assignment 162")

    bookings = _load_exact_rows(db, "cab_bookings", EXPECTED_BOOKINGS)
    sos_rows = _load_exact_rows(db, "crew_sos_requests", EXPECTED_SOS)
    incidents = _load_exact_rows(db, "incidents", EXPECTED_INCIDENTS)
    for row_id, expected in EXPECTED_BOOKINGS.items():
        _assert_exact(bookings[row_id], expected, f"booking {row_id}")
    for row_id, expected in EXPECTED_SOS.items():
        _assert_exact(sos_rows[row_id], expected, f"SOS {row_id}")
    for row_id, expected in EXPECTED_INCIDENTS.items():
        _assert_exact(incidents[row_id], expected, f"incident {row_id}")

    print("KONA REPAIR")
    print("  bookings: 325, 326")
    print("  SOS: 38")
    print("  incidents: 83, 84, 85")
    print("  target: vessel=149 call=134 agency=5 assignment=162 port=", call["port_id"])
    if not apply:
        return

    common = {
        **KONA_CONTEXT,
        "port_id": call["port_id"],
        "context_resolution": "manual_trip_record",
    }
    db.execute(text("""
        UPDATE cab_bookings
        SET vessel_id=:vessel_id, vessel_call_id=:vessel_call_id,
            agency_id=:agency_id, crew_assignment_id=:crew_assignment_id,
            port_id=:port_id, context_resolution=:context_resolution
        WHERE id = ANY(:ids)
    """), {**common, "ids": list(EXPECTED_BOOKINGS)})

    for record_id, previous_row in bookings.items():
        previous = {
            key: previous_row.get(key)
            for key in (
                "vessel_id", "vessel_call_id", "agency_id",
                "crew_assignment_id", "port_id", "context_resolution",
            )
        }
        resolved = {key: common[key] for key in previous}
        _audit_record(
            db,
            kind="booking",
            record_id=record_id,
            previous=previous,
            resolved=resolved,
            actor_user_id=actor_user_id,
        )

    for table, rows, kind in (
        ("crew_sos_requests", sos_rows, "sos"),
        ("incidents", incidents, "incident"),
    ):
        for record_id, previous_row in rows.items():
            previous = {
                key: previous_row.get(key)
                for key in (
                    "vessel_id", "vessel_call_id", "agency_id",
                    "crew_assignment_id", "port_id", "context_resolution",
                )
            }
            resolved = {key: common[key] for key in previous}
            _audit_record(
                db,
                kind=kind,
                record_id=record_id,
                previous=previous,
                resolved=resolved,
                actor_user_id=actor_user_id,
            )
        db.execute(text(f"""
            UPDATE {table}
            SET vessel_id=:vessel_id, vessel_call_id=:vessel_call_id,
                agency_id=:agency_id, crew_assignment_id=:crew_assignment_id,
                port_id=:port_id, context_resolution=:context_resolution
            WHERE id = ANY(:ids)
        """), {**common, "ids": list(rows)})

    db.execute(text("""
        UPDATE crew_sos_requests
        SET vessel = :vessel_name, port_name = :port_name
        WHERE id = 38
    """), {
        "vessel_name": call["vessel_name"],
        "port_name": db.execute(
            text("SELECT port_name FROM vessel_calls WHERE id=134")
        ).scalar_one(),
    })


def _foreign_key_references(db, *, table: str, row_ids: Iterable[int]) -> list[dict[str, Any]]:
    inspector = inspect(db.get_bind())
    row_ids = list(row_ids)
    references: list[dict[str, Any]] = []
    for candidate in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(candidate):
            if foreign_key.get("referred_table") != table:
                continue
            if len(foreign_key["constrained_columns"]) != 1:
                raise RuntimeError(f"Composite FK to {table} is not supported: {candidate}")
            column = foreign_key["constrained_columns"][0]
            count = db.execute(
                text(f'SELECT count(*) FROM "{candidate}" WHERE "{column}" = ANY(:ids)'),
                {"ids": row_ids},
            ).scalar_one()
            if count:
                references.append({"table": candidate, "column": column, "count": count})
    return references


def plan_common_luck_140(db, *, apply: bool) -> None:
    call = _row_dict(db.execute(text("""
        SELECT call.id, call.vessel_id, call.agency_id, call.ended_at,
               vessel.status AS vessel_status, vessel.agent_id
        FROM vessel_calls AS call
        JOIN vessels AS vessel ON vessel.id=call.vessel_id
        WHERE call.id=140
    """)).one())
    _assert_exact(call, {
        "id": 140, "vessel_id": 71, "agency_id": None,
        "ended_at": None, "vessel_status": "Archived", "agent_id": None,
    }, "invalid Common Luck call 140")

    assignments = db.execute(text("""
        SELECT id FROM crew_assignments WHERE vessel_call_id=140 ORDER BY id
    """)).scalars().all()
    if len(assignments) != 25:
        raise RuntimeError(f"Expected 25 cloned assignments on call 140, found {len(assignments)}")

    call_refs = _foreign_key_references(db, table="vessel_calls", row_ids=[140])
    non_assignment_refs = [row for row in call_refs if row["table"] != "crew_assignments"]
    print("COMMON LUCK CALL 140 RETIREMENT")
    print("  cloned assignments:", len(assignments))
    print("  remaining non-assignment references:", non_assignment_refs or "none")
    if non_assignment_refs:
        raise RuntimeError(
            "Call 140 still has operational references. Apply the Kona repair first."
        )
    assignment_refs = _foreign_key_references(
        db, table="crew_assignments", row_ids=assignments
    )
    if assignment_refs:
        raise RuntimeError(f"Cloned assignments still have references: {assignment_refs}")
    if apply:
        db.execute(text("DELETE FROM crew_assignments WHERE vessel_call_id=140"))
        db.execute(text("DELETE FROM vessel_calls WHERE id=140"))


def plan_serenity_duplicates(db, *, apply: bool) -> None:
    calls = _load_exact_rows(db, "vessel_calls", SERENITY_EMPTY_CALL_IDS)
    keep = _row_dict(db.execute(text("""
        SELECT id, vessel_id, agency_id FROM vessel_calls WHERE id=131
    """)).one())
    _assert_exact(keep, {"id": 131, "vessel_id": 120, "agency_id": 6}, "Serenity call 131")
    for call_id, call in calls.items():
        _assert_exact(call, {"id": call_id, "vessel_id": 120, "agency_id": 6},
                      f"Serenity duplicate call {call_id}")
    assignments = db.execute(text("""
        SELECT id FROM crew_assignments
        WHERE vessel_call_id = ANY(:ids) ORDER BY id
    """), {"ids": list(SERENITY_EMPTY_CALL_IDS)}).scalars().all()
    if len(assignments) != 144:
        raise RuntimeError(
            "Expected six calls with 24 cloned assignments each (144 total), "
            f"found {len(assignments)}"
        )
    call_refs = _foreign_key_references(
        db, table="vessel_calls", row_ids=SERENITY_EMPTY_CALL_IDS
    )
    non_assignment_refs = [row for row in call_refs if row["table"] != "crew_assignments"]
    assignment_refs = _foreign_key_references(
        db, table="crew_assignments", row_ids=assignments
    )
    print("SERENITY DUPLICATE-CALL RETIREMENT")
    print("  keep call:", SERENITY_KEEP_CALL_ID)
    print("  remove calls:", ", ".join(map(str, SERENITY_EMPTY_CALL_IDS)))
    print("  cloned assignments:", len(assignments))
    print("  non-assignment call references:", non_assignment_refs or "none")
    print("  assignment references:", assignment_refs or "none")
    if non_assignment_refs or assignment_refs:
        raise RuntimeError("Serenity duplicate calls are not empty; refusing cleanup")
    if apply:
        db.execute(text("""
            DELETE FROM crew_assignments WHERE vessel_call_id = ANY(:ids)
        """), {"ids": list(SERENITY_EMPTY_CALL_IDS)})
        db.execute(text("""
            DELETE FROM vessel_calls WHERE id = ANY(:ids)
        """), {"ids": list(SERENITY_EMPTY_CALL_IDS)})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope", action="append",
        choices=("kona", "common-luck-140", "serenity-empty-calls"),
        help="Repair scope; repeat to select multiple. Default: plan all scopes.",
    )
    parser.add_argument("--apply", action="store_true", help="Commit selected repairs")
    parser.add_argument(
        "--actor-user-id",
        type=int,
        help=(
            "Superadmin user ID responsible for the audited repair. "
            "Required with --apply."
        ),
    )
    args = parser.parse_args()
    scopes = args.scope or ["kona", "common-luck-140", "serenity-empty-calls"]
    if args.apply and (args.actor_user_id is None or args.actor_user_id <= 0):
        parser.error("--apply requires a positive --actor-user-id")

    db = SessionLocal()
    try:
        # Serialize both plans and writes. Dry runs execute the same guarded SQL
        # in a transaction and roll it back, so later scopes see the exact state
        # that an all-scopes apply would produce (for example, call 140 after
        # the Kona records have been repointed).
        db.execute(text("SELECT pg_advisory_xact_lock(20260812, 1)"))
        execute_repairs = True
        if "kona" in scopes:
            plan_kona(
                db,
                apply=execute_repairs,
                actor_user_id=args.actor_user_id,
            )
        if "common-luck-140" in scopes:
            plan_common_luck_140(db, apply=execute_repairs)
        if "serenity-empty-calls" in scopes:
            plan_serenity_duplicates(db, apply=execute_repairs)
        if args.apply:
            db.commit()
            print("COMMITTED")
        else:
            db.rollback()
            print("DRY RUN ONLY — no rows changed; rerun selected scopes with --apply")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
