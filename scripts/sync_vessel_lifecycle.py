#!/usr/bin/env python3
"""Preview or apply the server-authoritative 24-hour ETD lifecycle."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models.vessel import Vessel  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.vessel_lifecycle import (  # noqa: E402
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
        changes = [
            (vessel.id, vessel.name, vessel.status, effective_vessel_status(vessel))
            for vessel in vessels
            if vessel.status != effective_vessel_status(vessel)
        ]
        for vessel_id, name, before, after in changes:
            print(f"{vessel_id} {name!r}: {before!r} -> {after!r}")
        if not changes:
            print("No lifecycle transitions pending")
            return 0
        if not args.apply:
            print(f"DRY RUN ONLY — {len(changes)} transition(s); rerun with --apply")
            return 0
        synchronize_vessel_lifecycle(db, vessels)
        db.commit()
        print(f"COMMITTED — {len(changes)} vessel transition(s)")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
