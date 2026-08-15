"""Bring crew-assignment eligibility back in line with the manifest.

Eligibility is stored on the manifest row the vessel screen edits and on the
crew assignment operational reports read. The eligibility toggle and the general
crew edit used to write only the manifest, so the two drifted: an agent marked
crew eligible, the vessel page showed it, and the report kept the stale value.

The code now syncs both. This repairs the rows that drifted before it did.

The manifest wins. It is what the agent last edited and what the vessel page
shows them; the assignment is the copy that failed to keep up. Only assignments
on **active** calls are touched — a departed call is a historical record and its
eligibility should stay as it stood.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/repair_assignment_eligibility.py
    PYTHONPATH=. python scripts/repair_assignment_eligibility.py --apply
"""
import argparse
import sys

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy import func

from app.db.session import SessionLocal
from app.db.models.crew_assignment import CrewAssignment
from app.db.models.vessel_call import VesselCall
from app.db.models.vessel_crew import VesselCrew


def _manifest_row(db, call, assignment):
    """The manifest row this assignment came from, by id then by HPID."""
    if assignment.vessel_crew_id:
        row = db.query(VesselCrew).filter(
            VesselCrew.id == assignment.vessel_crew_id).first()
        if row is not None:
            return row
    if assignment.hpid and assignment.hpid.strip():
        return db.query(VesselCrew).filter(
            VesselCrew.vessel_id == call.vessel_id,
            func.upper(func.trim(VesselCrew.hp_id)) == assignment.hpid.strip().upper(),
        ).first()
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write the corrections; otherwise report only")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        calls = db.query(VesselCall).filter(VesselCall.ended_at.is_(None)).all()
        fixes, unmatched = [], []

        for call in calls:
            assignments = db.query(CrewAssignment).filter(
                CrewAssignment.vessel_call_id == call.id,
                CrewAssignment.ended_at.is_(None),
            ).all()
            for assignment in assignments:
                row = _manifest_row(db, call, assignment)
                if row is None:
                    unmatched.append((call, assignment))
                    continue
                if bool(row.shore_pass_eligible) != bool(assignment.shore_pass_eligible):
                    fixes.append((call, assignment, bool(row.shore_pass_eligible)))

        if not fixes and not unmatched:
            print("Every active assignment already agrees with its manifest row.")
            return 0

        if fixes:
            print(f"{len(fixes)} assignment(s) disagree with the manifest:\n")
            current_call = None
            for call, assignment, wanted in fixes:
                if call.id != current_call:
                    print(f"  call {call.id} — {call.vessel_name}")
                    current_call = call.id
                print(f"    {assignment.crew_name[:30]:30} "
                      f"{bool(assignment.shore_pass_eligible)} -> {wanted}")

        if unmatched:
            print(f"\n{len(unmatched)} assignment(s) have no matching manifest row "
                  f"and are left alone:")
            for call, assignment in unmatched[:10]:
                print(f"    call {call.id} {assignment.crew_name[:30]:30} "
                      f"hpid={assignment.hpid or 'none'}")
            if len(unmatched) > 10:
                print(f"    … and {len(unmatched) - 10} more")

        if not args.apply:
            print("\nDry run. Re-run with --apply to write the corrections.")
            return 0

        for _, assignment, wanted in fixes:
            assignment.shore_pass_eligible = wanted
        db.commit()
        print(f"\nCorrected {len(fixes)} assignment(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
