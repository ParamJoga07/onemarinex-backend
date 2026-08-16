"""How many crew accounts share a passport number, and whether they are one person.

Making a passport unique per account sounds like a one-line constraint, but the
codebase already records that production contains reused passport values — it is
why manifest matching requires passport *plus* name *plus* nationality rather
than passport alone. A unique index added today would simply fail.

Two very different things produce a duplicate, and they need opposite fixes:

  * the same person registered twice, and the accounts should be merged
  * different people carry the same value, because it was mistyped or a
    placeholder was used, and the value should be corrected

Comparing the names on each side is what separates them, so this prints them
together rather than only a count.

Note that self-registration performs no duplicate check at all. The identity
conflict queue guards the agent's add-crew path only, so anything found here
arrived through sign-up.

Read-only.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/audit_duplicate_passports.py
    PYTHONPATH=. python scripts/audit_duplicate_passports.py --limit 100
"""
import argparse
import sys
from collections import defaultdict

import app.db.base  # noqa: F401 — registers every model on Base

from app.db.session import SessionLocal
from app.db.models.crew_profile import CrewProfile
from app.services.crew_identity import (
    normalize_passport_number,
    normalized_person_name,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=40,
                        help="how many duplicate groups to print")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        profiles = db.query(CrewProfile).all()
        groups = defaultdict(list)
        blank = 0
        for profile in profiles:
            key = normalize_passport_number(profile.passport_number)
            if not key:
                blank += 1
                continue
            groups[key].append(profile)

        duplicates = {k: v for k, v in groups.items() if len(v) > 1}

        print(f"{len(profiles)} crew profile(s); {blank} with no passport recorded.")
        print(f"{len(groups)} distinct passport value(s), "
              f"{len(duplicates)} of them used by more than one account.\n")

        if not duplicates:
            print("No duplicates. A unique constraint could be added safely.")
            return 0

        same_person = 0
        different_people = 0
        for key, rows in sorted(duplicates.items(), key=lambda kv: -len(kv[1])):
            names = {normalized_person_name(r.full_name) for r in rows}
            verdict = "same name" if len(names) == 1 else "DIFFERENT NAMES"
            if len(names) == 1:
                same_person += 1
            else:
                different_people += 1

        print(f"  {same_person} group(s) share a name — likely one person, mergeable")
        print(f"  {different_people} group(s) have different names — likely a bad "
              f"passport value, not a duplicate person\n")

        shown = 0
        for key, rows in sorted(duplicates.items(), key=lambda kv: -len(kv[1])):
            if shown >= args.limit:
                print(f"\n… and {len(duplicates) - shown} more group(s)")
                break
            shown += 1
            names = {normalized_person_name(r.full_name) for r in rows}
            verdict = "same name" if len(names) == 1 else "DIFFERENT NAMES"
            print(f"passport {key} — {len(rows)} accounts — {verdict}")
            for row in rows:
                print(f"    profile {row.id:<6} user {str(row.user_id):<6} "
                      f"hpid {row.hpid or '—':<24} "
                      f"{(row.full_name or '—')[:32]:<32} "
                      f"{row.nationality or '—'}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
