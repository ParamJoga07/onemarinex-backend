"""Re-stamp SOS alerts that a backfill filed under the wrong ship.

Seven alerts name MT. BABYLON or MV COMMON LUCK and display as MV JIM MING 82,
all through call 130. The live SOS path cannot produce that: it takes the call
and the vessel name from the same `event_context` result, so the two always
agree. These rows were written by the l3m4n5o6p7q8 backfill, whose first rule
takes the call from the alert's linked cab booking —

    UPDATE cab_bookings SET vessel_call_id = call.id
    FROM vessel_calls AS call
    WHERE booking.vessel_call_id IS NULL AND booking.vessel_id = call.vessel_id

— a join with no time window and no uniqueness check, so a booking on a vessel
with several calls took an arbitrary one. That rule ran before the safer
"exact stored vessel name" rule and won, and the alerts inherited the result.

The repair reads the alert's own `vessel` text, which is the event-time
snapshot written when the alert was raised and the one field the backfill never
touched, and moves the alert to the call of that name whose port time contains
it. Where that is not exactly one call, the alert is reported and left alone.

Dry run by default; --apply writes. Idempotent: an alert already agreeing with
its call is not a candidate, so re-running finds nothing to do.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/repair_sos_vessel_call.py
    PYTHONPATH=. python scripts/repair_sos_vessel_call.py --apply
"""
import argparse
import re
import sys

import app.db.base  # noqa: F401 — registers every model on Base

from app.db.session import SessionLocal
from app.db.models.crew_assignment import CrewAssignment
from app.db.models.crew_sos import CrewSos
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall


RULE = "=" * 78


def _key(name):
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _contains(call, moment):
    """Whether an alert at `moment` falls inside this call's time in port."""
    if moment is None:
        return False
    start = call.started_at or call.created_at or call.eta
    if start is not None and moment < start:
        return False
    end = call.ended_at or call.etd
    if end is not None and moment > end:
        return False
    return start is not None or end is not None


def plan(db):
    """(mismatched, planned, blocked) — reads only, decides nothing to write."""
    calls = db.query(VesselCall).all()
    calls_by_id = {c.id: c for c in calls}

    mismatched = []
    for sos in db.query(CrewSos).order_by(CrewSos.id).all():
        if not sos.vessel or not sos.vessel_call_id:
            continue
        call = calls_by_id.get(sos.vessel_call_id)
        if call is None or not call.vessel_name:
            continue
        if _key(call.vessel_name) == _key(sos.vessel):
            continue
        mismatched.append((sos, call))

    planned, blocked = [], []
    for sos, call in mismatched:
        matches = [
            c for c in calls
            if _key(c.vessel_name) == _key(sos.vessel) and _contains(c, sos.created_at)
        ]
        if len(matches) > 1:
            matches = _narrow_by_assignment(db, sos, matches) or matches
        if len(matches) == 1:
            planned.append((sos, call, matches[0]))
        else:
            blocked.append((sos, call, matches))
    return mismatched, planned, blocked


def _narrow_by_assignment(db, sos, matches):
    """The calls this alert's own crew member was actually signed onto.

    A ship can have two calls whose port times overlap — a visit that was never
    closed, and the real one. MT. BABYLON has exactly that, so six alerts have
    two candidate calls on time alone.

    Who was on the ship settles it better than when the alert was raised: an
    agent put this crew member on one of those calls and not the other. Where
    the assignments say the same thing as the clock, that is a real answer;
    where the crew member is on both, or on neither, this narrows nothing and
    the alert stays with a person.
    """
    if not sos.crew_profile_id:
        return []
    assigned_call_ids = {
        row.vessel_call_id for row in db.query(CrewAssignment).filter(
            CrewAssignment.crew_profile_id == sos.crew_profile_id,
            CrewAssignment.vessel_call_id.in_([c.id for c in matches]),
        ).all()
    }
    return [c for c in matches if c.id in assigned_call_ids]


def apply_plan(db, planned):
    """Move each alert onto the call whose ship it names."""
    for sos, _old, target in planned:
        sos.vessel_call_id = target.id
        sos.vessel_id = target.vessel_id
        sos.agency_id = target.agency_id
        sos.port_id = target.port_id
        # The old assignment belonged to the call this alert is leaving.
        # Re-resolve it against the new one, and rather than carry a foreign
        # assignment forward, clear it when the answer is not exactly one.
        assignments = db.query(CrewAssignment).filter(
            CrewAssignment.vessel_call_id == target.id,
            CrewAssignment.crew_profile_id == sos.crew_profile_id,
        ).all() if sos.crew_profile_id else []
        sos.crew_assignment_id = assignments[0].id if len(assignments) == 1 else None
        sos.context_resolution = "repaired_vessel_name"
    return len(planned)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the re-stamps (default is a dry run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        vessels_by_id = {v.id: v.name for v in db.query(Vessel).all()}
        mismatched, planned, blocked = plan(db)

        print()
        print(RULE)
        if not mismatched:
            print("No SOS alert disagrees with the call it is stamped with.")
            print(RULE)
            print()
            return 0
        print(f"{len(mismatched)} SOS alert(s) disagree with the call they carry")
        print()

        for sos, call, target in planned:
            print(f"  SOS {sos.id}: names '{sos.vessel}', stamped call {call.id} "
                  f"'{call.vessel_name}' (written as '{sos.context_resolution}')")
            print(f"      -> call {target.id} '{target.vessel_name}', "
                  f"vessel {target.vessel_id} "
                  f"{vessels_by_id.get(target.vessel_id, '?')}")
        for sos, call, matches in blocked:
            print(f"  SOS {sos.id}: names '{sos.vessel}', stamped call {call.id} "
                  f"'{call.vessel_name}' (written as '{sos.context_resolution}')")
            if not matches:
                print(f"      -> no call named '{sos.vessel}' covers "
                      f"{sos.created_at}; left alone")
            else:
                print(f"      -> raised {sos.created_at}; {len(matches)} calls "
                      f"cover it and the crew member's assignments do not "
                      f"separate them. Left alone:")
                for c in matches:
                    start = c.started_at or c.created_at or c.eta
                    end = c.ended_at or c.etd
                    assigned = db.query(CrewAssignment).filter(
                        CrewAssignment.vessel_call_id == c.id,
                        CrewAssignment.crew_profile_id == sos.crew_profile_id,
                    ).count() if sos.crew_profile_id else 0
                    print(f"           call {c.id:<5} {c.status or '?':<10} "
                          f"{start} -> {end or 'open'}"
                          f"{'   crew is assigned to this one' if assigned else ''}")

        print()
        print(RULE)
        print(f"{len(planned)} to re-stamp, {len(blocked)} left for a human")
        print()

        if not args.apply:
            print("Dry run. Re-run with --apply to write.")
            print(RULE)
            print()
            return 0

        written = apply_plan(db, planned)
        db.commit()
        print(f"Wrote {written} re-stamp(s).")
        print(RULE)
        print()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
