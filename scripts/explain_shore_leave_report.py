"""Explain why a shore leave report shows the numbers it shows.

"Nothing is being fetched" has several possible causes that look identical on
the printed sheet: the crew list has no registered accounts behind it, the
trips belong to a different vessel, or the day genuinely had no shore leave.
This walks the same joins the report walks and says which one it is.

Read-only.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/explain_shore_leave_report.py --vessel "MV COMMON LUCK"
    PYTHONPATH=. python scripts/explain_shore_leave_report.py --vessel-id 12 --date 2026-08-11
"""
import argparse
import sys

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy import func, or_

from app.db.session import SessionLocal
from app.db.models.cab_booking import CabBooking
from app.db.models.crew_sos import CrewSos
from app.db.models.shore_pass import ShorePass
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew
from app.services import crew_linkage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vessel", help="vessel name (exact, case-insensitive)")
    parser.add_argument("--vessel-id", type=int)
    parser.add_argument("--date", help="report date YYYY-MM-DD; defaults to today at the port")
    args = parser.parse_args()
    if not args.vessel and args.vessel_id is None:
        parser.error("give --vessel or --vessel-id")

    db = SessionLocal()
    try:
        query = db.query(Vessel)
        vessel = (
            query.filter(Vessel.id == args.vessel_id).first()
            if args.vessel_id is not None else
            query.filter(func.upper(func.trim(Vessel.name)) == args.vessel.strip().upper()).first()
        )
        if not vessel:
            print("No such vessel. Names on record:")
            for row in db.query(Vessel).order_by(Vessel.name).all():
                print(f"  [{row.id}] {row.name}")
            return 1

        print(f"=== {vessel.name} (id={vessel.id}, agent_id={vessel.agent_id}) ===\n")

        manifest = db.query(VesselCrew).filter(VesselCrew.vessel_id == vessel.id).all()
        roster = crew_linkage.vessel_roster(db, vessel)
        registered = [m for m in roster.members if m.profile_id]
        eligible = [m for m in roster.members if m.eligible]

        print("Crew list")
        print(f"  manifest rows           {len(manifest)}   <- 'crew onboard'")
        print(f"  eligible for shore leave{len(eligible):>4}   <- 'eligible for shore leave'")
        print(f"  with a registered account{len(registered):>3}")
        if not registered:
            print("\n  !! No manifest row matches a crew account by HPID or passport.")
            print("     Shore passes, trips and SOS all hang off the account, so every")
            print("     other figure on the report will be zero until they link up.")
            missing = [m for m in roster.members if not m.profile_id][:5]
            for m in missing:
                print(f"       {m.name or '(unnamed)'} — hpid {m.hpid or 'none'}")

        crew_ids = roster.profile_ids
        if not crew_ids:
            print("\nNothing further to check without linked accounts.")
            return 0

        print("\nActivity for these crew, all dates")
        passes = db.query(ShorePass).filter(ShorePass.crew_profile_id.in_(crew_ids)).count()
        sos = db.query(CrewSos).filter(CrewSos.crew_profile_id.in_(crew_ids)).count()
        trips = db.query(CabBooking).filter(CabBooking.crew_id.in_(crew_ids)).all()
        print(f"  shore passes            {passes}")
        print(f"  SOS alerts              {sos}")
        print(f"  cab bookings            {len(trips)}")

        if trips:
            mine = [t for t in trips if t.vessel_id in (None, vessel.id)]
            others = [t for t in trips if t.vessel_id not in (None, vessel.id)]
            print(f"    counted for this vessel {len(mine)}")
            print(f"    stamped to another      {len(others)}")
            if others:
                names = {v.id: v.name for v in db.query(Vessel).all()}
                print("\n  !! These crew have trips pinned to a different ship, so this")
                print("     report excludes them. That is correct if they transferred.")
                for t in others[:8]:
                    print(f"       {t.booking_id} -> {names.get(t.vessel_id, t.vessel_id)}")

            print("\n  Trip dates (most recent first)")
            for t in sorted(trips, key=lambda x: str(x.created_at), reverse=True)[:8]:
                when = t.trip_started_at or t.started_at or t.created_at
                status = getattr(t.status, "value", t.status)
                print(f"    {str(when)[:16]}  {t.booking_id}  {status}")
            print("\n  A report is for one day. If none of the dates above fall on the")
            print("  report date, zero trips is the right answer.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
