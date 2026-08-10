#!/usr/bin/env python3
"""Repair reviewed legacy HPID string references without reissuing identities.

The mapping file is JSON: {"OLD-HPID": "CURRENT-HPID"}. Every target must
already belong to exactly one CrewProfile. Dry-run is the default.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.base import Base  # noqa: F401
from app.db.session import SessionLocal
from app.db.models.agent_roster_event import AgentRosterEvent
from app.db.models.crew_profile import CrewProfile
from app.db.models.incident import Incident
from app.db.models.vessel_crew import VesselCrew


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mapping")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with open(args.mapping, encoding="utf-8") as handle:
        mapping = json.load(handle)
    if not isinstance(mapping, dict) or not mapping:
        parser.error("mapping must be a non-empty JSON object")
    db = SessionLocal()
    try:
        plan = []
        for old, current in mapping.items():
            profile_count = db.query(CrewProfile).filter(CrewProfile.hpid == current).count()
            if profile_count != 1:
                raise ValueError(f"Target {current!r} must resolve to exactly one crew profile")
            for model, field in (
                (VesselCrew, "hp_id"),
                (Incident, "reporter_id"),
                (AgentRosterEvent, "subject_hpid"),
            ):
                query = db.query(model).filter(getattr(model, field) == old)
                count = query.count()
                if count:
                    plan.append({"old": old, "current": current, "table": model.__tablename__, "column": field, "count": count})
                    if args.apply:
                        query.update({field: current}, synchronize_session=False)
        print(json.dumps(plan, indent=2))
        if args.apply:
            db.commit()
            print("COMMITTED")
        else:
            db.rollback()
            print("DRY RUN ONLY — no HPID references changed")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
