"""Vessels a superadmin created that were never given to their agency.

The superadmin vessel form sends an agency name and no agent id. Until this was
fixed the handler fell back to the superadmin's own id whenever that name failed
to resolve to a profile, so the vessel was created, reported as created, and
belonged to a user who is not an agent — invisible on the agency's dashboard and
absent from its mapped vessels.

This finds those vessels and, with --apply, hands each to the agency its own
agency_name records. A vessel whose name matches no agency, or matches more than
one, is reported and left alone.

It also lists the agency names that would defeat an exact-match lookup — the
ones carrying leading or trailing whitespace, and any name registered twice —
since those are what made the lookup miss in the first place.

Dry run by default. Idempotent.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/repair_vessel_agency_assignment.py
    PYTHONPATH=. python scripts/repair_vessel_agency_assignment.py --apply
"""
import argparse
import sys
from collections import defaultdict

import app.db.base  # noqa: F401 — registers every model on Base

from app.db.session import SessionLocal
from app.db.models.agent_profile import AgentProfile
from app.db.models.user import User
from app.db.models.vessel import Vessel

RULE = "=" * 78


def _key(name):
    return (name or "").strip().lower()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the reassignments (default is a dry run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        profiles = db.query(AgentProfile).all()
        by_name = defaultdict(list)
        for p in profiles:
            by_name[_key(p.agency_name)].append(p)

        print()
        print(RULE)
        print("Agency names that defeat an exact-match lookup")
        print()
        untidy = [p for p in profiles
                  if (p.agency_name or "") != (p.agency_name or "").strip()]
        duplicated = {n: ps for n, ps in by_name.items()
                      if n and len({p.user_id for p in ps}) > 1}
        if not untidy and not duplicated:
            print("  None. Every agency name is tidy and unique.")
        for p in untidy:
            print(f"  agency {p.id}: '{p.agency_name}' has surrounding whitespace")
        for name, ps in duplicated.items():
            print(f"  '{ps[0].agency_name}' is registered by "
                  f"{len({p.user_id for p in ps})} different agents: "
                  f"{sorted({p.user_id for p in ps})}")

        agent_ids = {u.id for u in db.query(User).filter(User.role == "agent").all()}
        stranded = [
            v for v in db.query(Vessel).all()
            if v.agent_id is not None and v.agent_id not in agent_ids
        ]

        print()
        print(RULE)
        print("Vessels held by a user who is not an agent")
        print()
        if not stranded:
            print("  None.")
            print()
            print(RULE)
            print("Read-only. Nothing above has been written.")
            print()
            return 0

        planned, blocked = [], []
        for v in stranded:
            owners = by_name.get(_key(v.agency_name), [])
            distinct = {p.user_id for p in owners}
            print(f"  vessel {v.id:<6} '{v.name}'  IMO {v.imo_number}  "
                  f"held by user {v.agent_id}")
            print(f"      its agency_name reads '{v.agency_name}'")
            if len(distinct) == 1:
                target = owners[0].user_id
                print(f"      -> agency {owners[0].id}, agent user {target}")
                planned.append((v, target))
            elif not distinct:
                print("      -> no agency of that name; left alone")
                blocked.append(v)
            else:
                print(f"      -> {len(distinct)} agencies of that name; "
                      f"a person must choose. Left alone")
                blocked.append(v)

        print()
        print(RULE)
        print(f"{len(planned)} to reassign, {len(blocked)} left for a human")
        print()
        if not args.apply:
            print("Dry run. Re-run with --apply to write.")
            print(RULE)
            print()
            return 0

        for vessel, target in planned:
            vessel.agent_id = target
        db.commit()
        print(f"Reassigned {len(planned)} vessel(s).")
        print(RULE)
        print()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
