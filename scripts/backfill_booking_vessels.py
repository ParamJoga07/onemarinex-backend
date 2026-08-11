"""Stamp the vessel on cab bookings made before the column existed.

`cab_bookings.vessel_id` pins a trip to the ship it was taken from. Rows written
before it existed are NULL, and a NULL booking is counted by *every* vessel the
crew member is linked to — so reports for past dates still show one booking as
several trips, which is the defect the column was added to fix.

This does not guess. It resolves each booking's crew through the manifests and
stamps the trip only when that crew member appears on **exactly one** vessel.
Crew on several manifests are precisely the ambiguous case, and are left NULL:
the report falls back to crew linkage for them, which is no worse than today.

One caveat worth knowing. A crew member on exactly one manifest *now* may have
sailed elsewhere when the booking was made — nothing records where they were at
the time. Their current ship is the best evidence available and is strictly
better than NULL, which counts the trip on every ship at once.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/backfill_booking_vessels.py
    PYTHONPATH=. python scripts/backfill_booking_vessels.py --apply
"""
import argparse
import sys
from collections import Counter

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy import func

from app.db.session import SessionLocal
from app.db.models.cab_booking import CabBooking
from app.db.models.crew_profile import CrewProfile
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew


def _vessel_ids_for(db, crew) -> set:
    """Every vessel whose manifest lists this crew member."""
    if crew is None:
        return set()
    found = set()
    for value in (crew.hpid, crew.passport_number):
        if not value or not str(value).strip():
            continue
        needle = str(value).strip().upper()
        found.update(
            row[0] for row in db.query(VesselCrew.vessel_id).filter(
                func.upper(func.trim(VesselCrew.hp_id)) == needle
            ).all()
        )
        found.update(
            row[0] for row in db.query(VesselCrew.vessel_id).filter(
                func.upper(func.trim(VesselCrew.passport_number)) == needle
            ).all()
        )
    return {v for v in found if v is not None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write the stamps; otherwise report only")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        pending = db.query(CabBooking).filter(CabBooking.vessel_id.is_(None)).all()
        if not pending:
            print("Every booking already carries a vessel. Nothing to do.")
            return 0

        names = {v.id: v.name for v in db.query(Vessel).all()}
        crew_cache = {}
        resolved, ambiguous, unlinked = [], [], []

        for booking in pending:
            crew = crew_cache.get(booking.crew_id)
            if crew is None:
                crew = db.query(CrewProfile).filter(
                    CrewProfile.id == booking.crew_id).first()
                crew_cache[booking.crew_id] = crew
            vessel_ids = _vessel_ids_for(db, crew)
            if len(vessel_ids) == 1:
                resolved.append((booking, next(iter(vessel_ids))))
            elif len(vessel_ids) > 1:
                ambiguous.append((booking, vessel_ids))
            else:
                unlinked.append(booking)

        print(f"{len(pending)} booking(s) with no vessel stamp:")
        print(f"  {len(resolved)} resolvable — crew on exactly one manifest")
        print(f"  {len(ambiguous)} ambiguous — crew on several, left as-is")
        print(f"  {len(unlinked)} unlinked — crew on no manifest, left as-is")

        if resolved:
            tally = Counter(names.get(vid, f"vessel {vid}") for _, vid in resolved)
            print("\nWould stamp:")
            for name, count in sorted(tally.items()):
                print(f"  {count:>4}  {name}")

        if ambiguous:
            print("\nLeft ambiguous (these are the case the column exists for):")
            for booking, vessel_ids in ambiguous[:10]:
                listed = ", ".join(sorted(names.get(v, str(v)) for v in vessel_ids))
                print(f"  {booking.booking_id} — crew is on: {listed}")
            if len(ambiguous) > 10:
                print(f"  … and {len(ambiguous) - 10} more")

        if not args.apply:
            print("\nDry run. Re-run with --apply to write the stamps.")
            return 0

        for booking, vessel_id in resolved:
            booking.vessel_id = vessel_id
        db.commit()
        print(f"\nStamped {len(resolved)} booking(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
