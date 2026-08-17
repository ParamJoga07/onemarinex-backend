#!/usr/bin/env python3
"""Preview or apply the server-authoritative ETD lifecycle.

The departing window is whatever `DEPARTING_WINDOW` says; naming a duration
here only invited it to go stale, which it did.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models.vessel import Vessel  # noqa: E402
from app.db.models.vessel_call import VesselCall  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.vessel_lifecycle import (  # noqa: E402
    call_closed_by_the_clock,
    effective_vessel_status,
    synchronize_vessel_lifecycle,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        vessels = db.query(Vessel).order_by(Vessel.id).all()
        now = datetime.now(timezone.utc)
        active_calls = {
            call.vessel_id: call
            for call in db.query(VesselCall).filter(VesselCall.ended_at.is_(None)).all()
            if call.vessel_id is not None
        }
        changes = [
            (vessel.id, vessel.name, vessel.status, effective_vessel_status(vessel, now=now))
            for vessel in vessels
            if vessel.status != effective_vessel_status(vessel, now=now)
        ]
        call_changes = []
        for vessel in vessels:
            status = effective_vessel_status(vessel, now=now)
            call = active_calls.get(vessel.id)
            if status == "Departed" and call is not None:
                call_changes.append((vessel.id, "close active vessel call"))
            elif status in {"Active", "Departing"} and vessel.agent_id is not None:
                if call is None:
                    # A vessel with history no longer has a call manufactured
                    # for it. Either the departure the clock recorded is undone,
                    # or nothing happens — and the preview has to say which,
                    # because this script writes to production.
                    reopen = call_closed_by_the_clock(db, vessel, now)
                    if reopen is not None:
                        call_changes.append(
                            (vessel.id, f"reopen call {reopen.id} (ETD moved forward)")
                        )
                    elif not db.query(VesselCall.id).filter(
                        VesselCall.vessel_id == vessel.id
                    ).first():
                        call_changes.append((vessel.id, "create first vessel call"))
                elif call.status != status.upper():
                    call_changes.append((vessel.id, f"call status -> {status.upper()}"))
        for vessel_id, name, before, after in changes:
            print(f"{vessel_id} {name!r}: {before!r} -> {after!r}")
        for vessel_id, description in call_changes:
            print(f"{vessel_id} call: {description}")
        if not changes and not call_changes:
            print("No lifecycle transitions pending")
            db.rollback()
            return 0
        if not args.apply:
            print(
                "DRY RUN ONLY — "
                f"{len(changes)} vessel and {len(call_changes)} call transition(s); "
                "rerun with --apply"
            )
            db.rollback()
            return 0
        synchronize_vessel_lifecycle(db, vessels, now=now)
        db.commit()
        print(
            f"COMMITTED — {len(changes)} vessel and "
            f"{len(call_changes)} call transition(s)"
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
