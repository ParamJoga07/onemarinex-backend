"""Which day of a port call shows which shore leave numbers.

The report covers one calendar day at the port, and nothing on the printed
sheet says which day held any activity. A call whose trips all ran on the 11th
reads 0/0/0 on every other date, which looks identical to "nothing is being
fetched".

This runs the *real* report function once per day of the call, so the figures
below are exactly what the agent would see on screen — not a reimplementation
that could drift from it.

Read-only. Nothing is written and no session is committed.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/explain_shore_leave_days.py --call 142
    PYTHONPATH=. python scripts/explain_shore_leave_days.py --vessel "WAN HAI" --all-days
"""
import argparse
import sys
from datetime import timedelta
from types import SimpleNamespace

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy import func

from app.db.session import SessionLocal
from app.db.models.agent_profile import AgentProfile
from app.db.models.cab_booking import CabBooking
from app.db.models.crew_assignment import CrewAssignment
from app.db.models.vessel_call import VesselCall

MAX_DAYS = 90


def _calls(db, args):
    query = db.query(VesselCall)
    if args.call is not None:
        return query.filter(VesselCall.id == args.call).all()
    return (
        query.filter(func.upper(VesselCall.vessel_name).like(f"%{args.vessel.upper()}%"))
        .order_by(VesselCall.id)
        .all()
    )


def _agent_for(db, call):
    """A stand-in for the signed-in agent whose report this would be.

    `shore_leave_report` reads only the id and the agent profile off the user,
    and scopes everything to that profile — so borrowing the call's own agency
    reproduces what that agency sees, without needing a password.
    """
    if call.agency_id is None:
        return None, "call has no agency_id, so no agent can run this report"
    profile = db.query(AgentProfile).filter(AgentProfile.id == call.agency_id).first()
    if profile is None:
        return None, f"agency_id {call.agency_id} has no agent profile"
    return SimpleNamespace(
        id=profile.user_id, role="agent", agent_profile=profile,
    ), None


def _day_range(call):
    start = call.eta or call.started_at or call.created_at
    end = call.ended_at or call.etd or start
    if start is None or end is None:
        return []
    if end < start:
        start, end = end, start
    days, cursor = [], start.date()
    while cursor <= end.date() and len(days) < MAX_DAYS:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--call", type=int, help="vessel call id")
    parser.add_argument("--vessel", help="vessel name fragment, case-insensitive")
    parser.add_argument("--all-days", action="store_true",
                        help="print every day, not only those with activity")
    args = parser.parse_args()
    if args.call is None and not args.vessel:
        parser.error("give --call or --vessel")

    from app.api.v1.routes_agents import shore_leave_report

    db = SessionLocal()
    try:
        calls = _calls(db, args)
        if not calls:
            print("No matching vessel call.")
            return 1

        for call in calls:
            crew = db.query(func.count(CrewAssignment.id)).filter(
                CrewAssignment.vessel_call_id == call.id).scalar() or 0
            eligible = db.query(func.count(CrewAssignment.id)).filter(
                CrewAssignment.vessel_call_id == call.id,
                CrewAssignment.shore_pass_eligible.is_(True),
            ).scalar() or 0
            bookings = db.query(func.count(CabBooking.id)).filter(
                CabBooking.vessel_call_id == call.id).scalar() or 0

            print(f"\n{'=' * 78}")
            print(f"call {call.id} — {call.vessel_name} (IMO {call.imo_number or '—'})")
            print(f"  agency_id {call.agency_id}  status {call.status}  "
                  f"ended {call.ended_at or 'open'}")
            print(f"  {crew} crew on the roster, {eligible} eligible, "
                  f"{bookings} booking(s) attached")

            agent, problem = _agent_for(db, call)
            if agent is None:
                print(f"  cannot run the report: {problem}")
                continue

            days = _day_range(call)
            if not days:
                print("  the call has no dates to walk")
                continue

            print(f"\n  {'date':12} {'went':>5} {'back':>5} {'still':>6} "
                  f"{'trips':>6} {'util':>5} {'avg min':>8}  sos/inc")
            print(f"  {'-' * 68}")
            shown = 0
            for day in days:
                stamp = day.isoformat()
                try:
                    row = shore_leave_report(
                        vessel_id=call.vessel_id, report_date=stamp,
                        vessel_call_id=call.id, db=db, current_user=agent,
                    )
                except Exception as exc:  # noqa: BLE001 — surfaced, not swallowed
                    print(f"  {stamp:12} report failed: {exc}")
                    continue
                busy = (row.crew_went_ashore or row.completed_trips
                        or row.sos_raised or row.incidents_reported)
                if not busy and not args.all_days:
                    continue
                shown += 1
                average = ("—" if row.average_duration_minutes is None
                           else f"{row.average_duration_minutes:.1f}")
                print(f"  {stamp:12} {row.crew_went_ashore:>5} {row.returned_safely:>5} "
                      f"{row.still_ashore:>6} {row.completed_trips:>6} "
                      f"{row.shore_leave_utilisation_pct:>4}% {average:>8}  "
                      f"{row.sos_raised}/{row.incidents_reported}")
            if not shown:
                print("  no day in this call recorded any shore leave activity")
            elif not args.all_days:
                print(f"\n  ({len(days) - shown} quiet day(s) hidden; "
                      f"--all-days shows them)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
