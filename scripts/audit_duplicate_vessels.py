"""Ships recorded twice, and IMO numbers that cannot be right.

MT BABYLON exists as two vessel rows — one under agency "Other" owned by the
superadmin, one under Praveen Shipping — because their IMO numbers differ. The
unique index on imo_number cannot catch that, so a ship split in two takes its
crew, trips and safety records with it, and each half looks under-reported.

One of those IMOs is six digits. A real IMO is seven, the last of which is a
check digit computed from the first six, so a malformed number is detectable
rather than merely suspicious — and a typo there is exactly what lets the same
ship in twice.

Groups vessels by name compared without case, spacing or punctuation, since
"MT BABYLON" and "MT. BABYLON" are the same ship to everyone but the database.

Read-only.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/audit_duplicate_vessels.py
    PYTHONPATH=. python scripts/audit_duplicate_vessels.py --imo-only
"""
import argparse
import re
import sys
from collections import defaultdict

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy import func

from app.db.session import SessionLocal
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall


def _name_key(name):
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


def _imo_verdict(imo):
    """Whether an IMO number can be genuine.

    IMO 9379519: 9x7 + 3x6 + 7x5 + 9x4 + 5x3 + 1x2 = 169, and the seventh digit
    is 9, so it checks out. The check digit makes a typo detectable rather than
    merely suspicious, which is worth saying out loud when two rows for one ship
    differ only by their number.
    """
    digits = re.sub(r"\D", "", (imo or ""))
    if not digits:
        return "no digits"
    if len(digits) != 7:
        return f"{len(digits)} digits, not 7"
    total = sum(int(digits[i]) * (7 - i) for i in range(6))
    return "valid" if total % 10 == int(digits[6]) else "check digit fails"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--imo-only", action="store_true",
                        help="only report malformed IMO numbers")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        vessels = db.query(Vessel).order_by(Vessel.id).all()
        calls = defaultdict(int)
        for vessel_id, count in (
            db.query(VesselCall.vessel_id, func.count(VesselCall.id))
            .group_by(VesselCall.vessel_id).all()
        ):
            calls[vessel_id] = count

        suspect = [(v, _imo_verdict(v.imo_number)) for v in vessels]
        malformed = [(v, why) for v, why in suspect if why != "valid"]

        print(f"{len(vessels)} vessel(s).\n")
        print(f"{'=' * 78}")
        print(f"IMO numbers that cannot be genuine: {len(malformed)}")
        for vessel, why in malformed:
            print(f"  vessel {vessel.id:<5} {(vessel.name or '—')[:30]:<30} "
                  f"imo {str(vessel.imo_number)[:14]:<14} {why}")
        if not malformed:
            print("  None — every IMO is seven digits with a valid check digit.")

        if args.imo_only:
            return 0

        groups = defaultdict(list)
        for vessel in vessels:
            key = _name_key(vessel.name)
            if key:
                groups[key].append(vessel)
        duplicates = {k: v for k, v in groups.items() if len(v) > 1}

        print(f"\n{'=' * 78}")
        print(f"Ships recorded more than once under the same name: {len(duplicates)}")
        if not duplicates:
            print("  None.")
            return 0

        for key, rows in sorted(duplicates.items(), key=lambda kv: -len(kv[1])):
            print(f"\n  {rows[0].name} — {len(rows)} rows")
            for vessel in rows:
                print(f"    vessel {vessel.id:<5} imo {str(vessel.imo_number)[:14]:<14} "
                      f"({_imo_verdict(vessel.imo_number):<18}) "
                      f"agency {(vessel.agency_name or '—')[:22]:<22} "
                      f"{vessel.status or '—':<9} "
                      f"{calls.get(vessel.id, 0)} call(s)")
            print("    -> merging these means moving calls, crew, trips and safety "
                  "records onto one row; the other is then archived, not deleted.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
