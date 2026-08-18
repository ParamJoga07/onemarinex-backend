"""Move one vessel's history onto another and archive the duplicate.

MT BABYLON exists twice: vessel 77 under IMO 9379519, and vessel 151 under
985478. Six digits is not an IMO — a real one is seven, the last a check digit
over the first six — so the unique index never saw a collision and let the same
ship in a second time. A split ship splits its calls, crew, trips and safety
records with it, and each half then under-reports.

Merging moves everything that points at the duplicate onto the survivor, then
archives the duplicate rather than deleting it. Archiving keeps the row
reachable if the merge turns out to have been wrong; a delete would take its
foreign keys with it and there would be nothing to inspect.

The survivor is the one whose IMO can actually be an IMO. Where both are valid
the caller has to say, because nothing in the data can.

Read-only until --apply.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/merge_duplicate_vessel.py --into 77 --from 151
    PYTHONPATH=. python scripts/merge_duplicate_vessel.py --into 77 --from 151 --apply
"""
import argparse
import re
import sys

import app.db.base  # noqa: F401 — registers every model on Base

from app.db.session import SessionLocal
from app.db.models.cab_booking import CabBooking
from app.db.models.crew_sos import CrewSos
from app.db.models.incident import Incident
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall
from app.db.models.vessel_crew import VesselCrew


def _imo_verdict(imo) -> str:
    digits = re.sub(r"\D", "", str(imo or ""))
    if not digits:
        return "no digits"
    if len(digits) != 7:
        return f"{len(digits)} digits, not 7"
    total = sum(int(digits[i]) * (7 - i) for i in range(6))
    return "valid" if total % 10 == int(digits[6]) else "check digit fails"


# Everything that names a vessel. Kept as an explicit list rather than walking
# the metadata, so a table added later shows up as a review of this file rather
# than as a silent no-op that leaves records behind on the archived row.
MOVES = (
    ("vessel calls", VesselCall, "vessel_id"),
    ("crew manifest rows", VesselCrew, "vessel_id"),
    ("cab bookings", CabBooking, "vessel_id"),
    ("incidents", Incident, "vessel_id"),
    ("SOS alerts", CrewSos, "vessel_id"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--into", type=int, required=True,
                        help="the vessel id that survives")
    parser.add_argument("--from", dest="source", type=int, required=True,
                        help="the duplicate whose records move across")
    parser.add_argument("--apply", action="store_true",
                        help="write the changes; otherwise report only")
    args = parser.parse_args()

    if args.into == args.source:
        print("A vessel cannot be merged into itself.")
        return 1

    db = SessionLocal()
    try:
        survivor = db.query(Vessel).filter(Vessel.id == args.into).first()
        duplicate = db.query(Vessel).filter(Vessel.id == args.source).first()
        if survivor is None or duplicate is None:
            print(f"Vessel {args.into if survivor is None else args.source} not found.")
            return 1

        print(f"survivor   {survivor.id:<5} {(survivor.name or '-')[:28]:<28} "
              f"imo {str(survivor.imo_number)[:14]:<14} ({_imo_verdict(survivor.imo_number)})")
        print(f"duplicate  {duplicate.id:<5} {(duplicate.name or '-')[:28]:<28} "
              f"imo {str(duplicate.imo_number)[:14]:<14} ({_imo_verdict(duplicate.imo_number)})")

        if _imo_verdict(survivor.imo_number) != "valid":
            print("\nWARNING: the survivor's IMO is not a valid one. Check that "
                  "the two ids are the right way round before applying.")

        print()
        total = 0
        for label, model, column in MOVES:
            count = db.query(model).filter(
                getattr(model, column) == duplicate.id).count()
            total += count
            print(f"  {count:>4} {label} would move to vessel {survivor.id}")

        # An open call on each would leave the survivor with two, which is the
        # state the returning-vessel path refuses for good reason.
        open_on_survivor = db.query(VesselCall).filter(
            VesselCall.vessel_id == survivor.id, VesselCall.ended_at.is_(None)).count()
        open_on_duplicate = db.query(VesselCall).filter(
            VesselCall.vessel_id == duplicate.id, VesselCall.ended_at.is_(None)).count()
        if open_on_survivor and open_on_duplicate:
            print(f"\nBoth vessels have an open call ({open_on_survivor} and "
                  f"{open_on_duplicate}). Merging would leave one hull with two "
                  f"live calls, which splits its crew and trips exactly as this "
                  f"merge is meant to stop. Close one first.")
            return 1

        if not args.apply:
            print(f"\nDry run. {total} record(s) would move, and vessel "
                  f"{duplicate.id} would be archived. Re-run with --apply.")
            return 0

        for label, model, column in MOVES:
            db.query(model).filter(getattr(model, column) == duplicate.id).update(
                {column: survivor.id}, synchronize_session="fetch")

        # Archived, not deleted: the row stays reachable if this was wrong, and
        # the vessel list already excludes archived ships from selection.
        duplicate.status = "Archived"
        duplicate.agent_id = None
        db.commit()
        print(f"\nMoved {total} record(s) onto vessel {survivor.id}; "
              f"vessel {duplicate.id} archived.")

        left = sum(
            db.query(model).filter(getattr(model, column) == duplicate.id).count()
            for _, model, column in MOVES
        )
        if left:
            print(f"WARNING: {left} record(s) still point at the archived vessel.")
            return 1
        print("Nothing points at the archived vessel any more.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
