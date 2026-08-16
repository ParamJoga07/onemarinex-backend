"""SOS alerts and incidents that carry no owner, and where they would belong.

Release A stamps every new safety record with the vessel, agency and call it
happened on. Records written before that carry nothing, and two symptoms follow
from the same gap:

  * the agent dashboard headline counts rows whose agency_id is null, while the
    vessel cards require both agency_id and vessel_id to match — so the same
    screen shows "3 open" beside a vessel card reading 0
  * with no owner stamped, a display that falls back to identity inference
    attaches an alert to whichever ship its crew member most recently joined,
    which is how one vessel's alerts appear under another

This reports the size of the backlog and, for each unowned record, the vessel
its crew member can actually be traced to. It proposes; it does not decide, and
it writes nothing.

Attribution is attempted in descending order of certainty: the assignment the
record already names, then the call whose time in port contains it, then the
vessel when every candidate call belongs to the same ship. A record that spans
two different ships is listed for a human rather than guessed at.

Read-only.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/audit_unowned_safety_records.py
    PYTHONPATH=. python scripts/audit_unowned_safety_records.py --limit 100
"""
import argparse
import sys
from datetime import timezone

import app.db.base  # noqa: F401 — registers every model on Base

from app.db.session import SessionLocal
from app.db.models.crew_assignment import CrewAssignment
from app.db.models.crew_sos import CrewSos
from app.db.models.incident import Incident
from app.db.models.vessel_call import VesselCall


def _traceable_calls(db, crew_profile_id):
    """Every vessel call this crew member has ever been assigned to."""
    if not crew_profile_id:
        return []
    rows = (
        db.query(VesselCall)
        .join(CrewAssignment, CrewAssignment.vessel_call_id == VesselCall.id)
        .filter(CrewAssignment.crew_profile_id == crew_profile_id)
        .order_by(VesselCall.id)
        .all()
    )
    seen, unique = set(), []
    for row in rows:
        if row.id not in seen:
            seen.add(row.id)
            unique.append(row)
    return unique


def _aware(value):
    """UTC-aware, whatever the column stored.

    `incidents.created_at` is `timestamp without time zone` while its
    neighbours are not, so a naive value here means UTC.
    """
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _call_covering(calls, when):
    """The one call whose time in port contains `when`, if exactly one does.

    Several calls for the same vessel are only ambiguous until you ask when the
    record happened: a ship is alongside once at a time, so the windows do not
    overlap and the timestamp picks the call out.
    """
    moment = _aware(when)
    if moment is None:
        return None
    matches = []
    for call in calls:
        start = _aware(call.started_at or call.eta or call.created_at)
        end = _aware(call.ended_at or call.etd)
        if start is not None and moment < start:
            continue
        if end is not None and moment > end:
            continue
        matches.append(call)
    return matches[0] if len(matches) == 1 else None


def _report(db, label, model, limit):
    total = db.query(model).count()
    unowned = db.query(model).filter(model.agency_id.is_(None)).all()
    no_vessel = db.query(model).filter(model.vessel_id.is_(None)).count()

    print(f"\n{'=' * 78}")
    print(f"{label}: {total} total, {len(unowned)} with no agency, "
          f"{no_vessel} with no vessel")
    if not unowned:
        print("  Nothing to reconcile.")
        return

    resolvable, one_vessel, ambiguous, untraceable = [], [], [], []
    for row in unowned:
        # An assignment names its own call, so a row that has one needs no
        # inference at all — it was written with the link but without the
        # denormalised owner columns the dashboard filters on.
        if row.crew_assignment_id:
            assignment = db.query(CrewAssignment).filter(
                CrewAssignment.id == row.crew_assignment_id).first()
            if assignment is not None and assignment.vessel_call is not None:
                resolvable.append((row, assignment.vessel_call))
                continue

        calls = _traceable_calls(db, row.crew_profile_id)
        if not calls:
            untraceable.append(row)
            continue
        if len(calls) == 1:
            resolvable.append((row, calls[0]))
            continue
        # Several calls. The timestamp usually settles it, because a ship is
        # alongside once at a time.
        covering = _call_covering(calls, getattr(row, "created_at", None))
        if covering is not None:
            resolvable.append((row, covering))
            continue
        # Still several, but if they are all the same ship then the vessel and
        # the agency are certain even though the call is not.
        vessels = {c.vessel_id for c in calls}
        if len(vessels) == 1:
            one_vessel.append((row, calls))
        else:
            ambiguous.append((row, calls))

    print(f"  {len(resolvable)} resolve to exactly one call — safe to stamp fully")
    print(f"  {len(one_vessel)} resolve to one vessel but not one call — "
          f"vessel and agency safe, call left null")
    print(f"  {len(ambiguous)} span different vessels — need a human to choose")
    print(f"  {len(untraceable)} trace to none — no assignment history at all")

    if one_vessel:
        print(f"\n  One vessel, call undecided:")
        for row, calls in one_vessel[:limit]:
            first = calls[0]
            print(f"    {label[:3]} {row.id:<6} -> vessel {first.vessel_id} "
                  f"{(first.vessel_name or '—')[:26]:<26} agency {first.agency_id} "
                  f"(calls {', '.join(str(c.id) for c in calls[:5])})")
        if len(one_vessel) > limit:
            print(f"    … and {len(one_vessel) - limit} more")

    if resolvable:
        print(f"\n  Would be stamped:")
        for row, call in resolvable[:limit]:
            print(f"    {label[:3]} {row.id:<6} -> call {call.id:<6} "
                  f"{(call.vessel_name or '—')[:28]:<28} agency {call.agency_id}")
        if len(resolvable) > limit:
            print(f"    … and {len(resolvable) - limit} more")

    if ambiguous:
        print(f"\n  Ambiguous — listing the candidates:")
        for row, calls in ambiguous[:limit]:
            names = ", ".join(
                f"call {c.id} {(c.vessel_name or '—')[:20]}" for c in calls[:4]
            )
            print(f"    {label[:3]} {row.id:<6} -> {names}")
        if len(ambiguous) > limit:
            print(f"    … and {len(ambiguous) - limit} more")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25,
                        help="how many rows to list per section")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        _report(db, "SOS alerts", CrewSos, args.limit)
        _report(db, "Incidents", Incident, args.limit)
        print(f"\n{'=' * 78}")
        print("Read-only. Nothing above has been written.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
