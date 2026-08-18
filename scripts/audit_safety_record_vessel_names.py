"""Safety records whose stamped vessel disagrees with the ship they name.

`audit_unowned_safety_records.py` asks which records carry no owner. This asks
a different question: of the records that *do* carry one, does the vessel they
resolve to still match the ship the record itself names?

That is the mechanism behind "SOS alerts of MT.Babylon & Common Luck are still
being appended to Jim Ming 82". An SOS keeps the vessel name as free text, but
every agent-facing screen resolves the vessel through `vessel_call_id`, and
failing that through `vessel_id` — which reads the vessel row's name *as it is
now*. So a vessel record that has been renamed, or reused for a second ship,
relabels every historical record pointing at it.

Three questions, in the order they need answering:

  1. Which SOS alerts display under a different ship than they name?
  2. Which vessel records have carried more than one ship's name across their
     calls? Those are what relabel the records in (1).
  3. Which crew members hold assignments on calls whose port times overlap?
     That is why the unowned audit cannot place 15 of its alerts: two calls are
     open around the same alert and both look equally plausible.

Read-only. It writes nothing and proposes nothing to write.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/audit_safety_record_vessel_names.py
"""
import re
import sys
from collections import defaultdict

import app.db.base  # noqa: F401 — registers every model on Base

from app.db.session import SessionLocal
from app.db.models.crew_assignment import CrewAssignment
from app.db.models.crew_profile import CrewProfile
from app.db.models.crew_sos import CrewSos
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall


RULE = "=" * 78


def _key(name):
    """Compare ship names the way a person reads them: MT. BABYLON == MT BABYLON."""
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _resolved_name(sos, calls_by_id, vessels_by_id):
    """The name the agent screens show, by the same route they take."""
    if sos.vessel_call_id:
        call = calls_by_id.get(sos.vessel_call_id)
        if call and call.vessel_name:
            return call.vessel_name, f"call {call.id}"
    if sos.vessel_id:
        vessel = vessels_by_id.get(sos.vessel_id)
        if vessel:
            return vessel.name, f"vessel {vessel.id}"
    return None, None


def _overlaps(a_start, a_end, b_start, b_end):
    if a_start is None or b_start is None:
        return False
    if a_end is not None and b_start > a_end:
        return False
    if b_end is not None and a_start > b_end:
        return False
    return True


def main():
    db = SessionLocal()
    try:
        vessels_by_id = {v.id: v for v in db.query(Vessel).all()}
        calls_by_id = {c.id: c for c in db.query(VesselCall).all()}

        # 1. Records that name one ship and display as another.
        print()
        print(RULE)
        print("SOS alerts whose displayed vessel differs from the one they name")
        print()
        mismatches = []
        unresolved = 0
        for sos in db.query(CrewSos).order_by(CrewSos.id).all():
            shown, via = _resolved_name(sos, calls_by_id, vessels_by_id)
            if shown is None:
                unresolved += 1
                continue
            if not sos.vessel:
                continue
            if _key(shown) != _key(sos.vessel):
                mismatches.append((sos, shown, via))

        if not mismatches:
            print("  None. Every resolvable alert displays under the ship it names.")
        else:
            print(f"  {len(mismatches)} alert(s):")
            print()
            print(f"    {'SOS':<8} {'names':<24} {'displays as':<24} via")
            for sos, shown, via in mismatches:
                print(f"    {sos.id:<8} {str(sos.vessel)[:23]:<24} {str(shown)[:23]:<24} {via}")
        if unresolved:
            print()
            print(f"  ({unresolved} alert(s) resolve to no vessel at all — those are the "
                  f"unowned backlog, see audit_unowned_safety_records.py)")

        # 2. Vessel records that have stood for more than one ship.
        print()
        print(RULE)
        print("Vessel records whose calls carry more than one ship name")
        print()
        names_by_vessel = defaultdict(set)
        for call in calls_by_id.values():
            if call.vessel_id and call.vessel_name:
                names_by_vessel[call.vessel_id].add(call.vessel_name)
        reused = {
            vid: names for vid, names in names_by_vessel.items()
            if len({_key(n) for n in names}) > 1
        }
        # A vessel currently named something no call of its own ever used is the
        # same fault seen from the other side.
        renamed = {
            vid: names for vid, names in names_by_vessel.items()
            if vid not in reused
            and vid in vessels_by_id
            and _key(vessels_by_id[vid].name) not in {_key(n) for n in names}
        }
        if not reused and not renamed:
            print("  None. Every vessel record has carried one ship throughout.")
        for vid, names in sorted(reused.items()):
            current = vessels_by_id[vid].name if vid in vessels_by_id else "?"
            print(f"  vessel {vid} is now '{current}'")
            for name in sorted(names):
                call_ids = sorted(
                    c.id for c in calls_by_id.values()
                    if c.vessel_id == vid and _key(c.vessel_name) == _key(name)
                )
                print(f"      calls {call_ids} were '{name}'")
        for vid, names in sorted(renamed.items()):
            current = vessels_by_id[vid].name if vid in vessels_by_id else "?"
            print(f"  vessel {vid} is now '{current}' but every call of its own "
                  f"reads '{sorted(names)[0]}'")

        # 3. Why the unowned alerts cannot be placed.
        print()
        print(RULE)
        print("Crew on calls whose port times overlap")
        print()
        rows = db.query(CrewAssignment).filter(
            CrewAssignment.crew_profile_id.isnot(None)
        ).all()
        by_crew = defaultdict(list)
        for row in rows:
            call = calls_by_id.get(row.vessel_call_id)
            if call is not None:
                by_crew[row.crew_profile_id].append(call)

        clashes = 0
        for crew_id, calls in sorted(by_crew.items()):
            seen = []
            for call in calls:
                start = call.started_at or call.created_at
                for other in seen:
                    other_start = other.started_at or other.created_at
                    if call.vessel_id == other.vessel_id:
                        continue
                    if _overlaps(start, call.ended_at, other_start, other.ended_at):
                        name = db.query(CrewProfile.full_name).filter(
                            CrewProfile.id == crew_id
                        ).scalar()
                        print(f"  crew {crew_id} {name or ''}".rstrip())
                        print(f"      call {other.id:<5} {other.vessel_name:<24} "
                              f"{other_start} -> {other.ended_at or 'open'}")
                        print(f"      call {call.id:<5} {call.vessel_name:<24} "
                              f"{start} -> {call.ended_at or 'open'}")
                        clashes += 1
                seen.append(call)
        if not clashes:
            print("  None. No crew member is on two ships at once.")

        print()
        print(RULE)
        print("Read-only. Nothing above has been written.")
        print()
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
