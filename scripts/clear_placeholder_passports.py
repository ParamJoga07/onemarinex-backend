"""Clear passport values that identify nobody, so uniqueness becomes reachable.

Production holds accounts under `U` and `NOT_PROVIDED`. They were accepted
because sign-up validated the email and the mobile number and nothing else, and
they are the only reason a unique index on `passport_number` cannot be added:
an audit found **no** two accounts sharing both a passport and a name, so there
are no duplicate people to merge — only placeholders colliding with each other.

Three different people share `U`.

What this does, and deliberately does not do
--------------------------------------------

It sets those values to NULL. Postgres permits many NULLs under a unique index,
so that alone unblocks the constraint.

By default it clears only outright placeholders — `NOT_PROVIDED`, `U`, and the
like — which carry no information to lose. A value that fails only for want of a
digit, such as `AANTRRC`, may be a real passport typed wrongly; clearing it
destroys the only clue to what it should have been, so it is reported for
correction instead. `--all-invalid` clears those too.

**It does not touch HPIDs.** An HPID derived from a placeholder is ugly —
`HP-U-IN-VIS` — but it is also the key that manifests, assignments, shore passes
and bookings were written against. Reissuing it to make it prettier would orphan
every one of those links. The identity stays; only the field that was never a
passport is cleared.

Nor does it invent a passport. Nobody knows what these people's real numbers
are, and NULL says that honestly where `U` claimed otherwise.

After this runs cleanly, the unique constraint can be added.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/clear_placeholder_passports.py
    PYTHONPATH=. python scripts/clear_placeholder_passports.py --apply
"""
import argparse
import sys
from collections import defaultdict

import app.db.base  # noqa: F401 — registers every model on Base

from app.db.session import SessionLocal
from app.db.models.crew_profile import CrewProfile
from app.services.crew_identity import (
    MINIMUM_PASSPORT_LENGTH,
    PLACEHOLDER_PASSPORTS,
    CrewIdentityConflict,
    normalize_passport_number,
    validate_passport_number,
)


def _is_placeholder(value) -> bool:
    """Whether the value was typed to skip the field rather than to identify.

    `NOT_PROVIDED` and `U` are placeholders on their face and carry no
    information to lose. A value that fails only for want of a digit —
    `AANTRRC`, `Hbbsxll` — is a different case: it may be a real passport typed
    wrongly, and clearing it destroys the only remaining clue to what it should
    have been.
    """
    passport = normalize_passport_number(value)
    if not passport:
        return True
    stripped = "".join(character for character in passport if character.isalnum())
    return (
        passport in PLACEHOLDER_PASSPORTS
        or stripped in PLACEHOLDER_PASSPORTS
        or len(stripped) < MINIMUM_PASSPORT_LENGTH
    )


def _linked_record_counts(db, profile):
    """What already points at this person, so the blast radius is visible."""
    from app.db.models.cab_booking import CabBooking
    from app.db.models.crew_assignment import CrewAssignment
    from app.db.models.shore_pass import ShorePass

    return {
        "assignments": db.query(CrewAssignment).filter(
            CrewAssignment.crew_profile_id == profile.id).count(),
        "passes": db.query(ShorePass).filter(
            ShorePass.crew_profile_id == profile.id).count(),
        "bookings": db.query(CabBooking).filter(
            CabBooking.crew_id == profile.id).count(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write the changes; otherwise report only")
    parser.add_argument("--all-invalid", action="store_true",
                        help="also clear invalid values that collide with "
                             "nothing, which the constraint does not require")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        profiles = db.query(CrewProfile).order_by(CrewProfile.id).all()

        unusable = []
        for profile in profiles:
            raw = profile.passport_number
            if raw is None or not str(raw).strip():
                continue
            try:
                validate_passport_number(raw)
            except CrewIdentityConflict as exc:
                unusable.append((profile, str(exc)))

        # Which of them are actually colliding, since that is what blocks the
        # constraint — a lone bad value is untidy but not an obstacle.
        groups = defaultdict(list)
        for profile in profiles:
            key = normalize_passport_number(profile.passport_number)
            if key:
                groups[key].append(profile)
        colliding = {k: v for k, v in groups.items() if len(v) > 1}

        placeholders = [(p, r) for p, r in unusable
                        if _is_placeholder(p.passport_number)]
        maybe_typos = [(p, r) for p, r in unusable
                       if not _is_placeholder(p.passport_number)]
        targets = unusable if args.all_invalid else placeholders

        print(f"{len(profiles)} crew profile(s).")
        print(f"{len(unusable)} hold a value that cannot be a passport.")
        print(f"{len(colliding)} passport value(s) are used by more than one "
              f"account.\n")

        if not unusable:
            print("Nothing to clear. A unique constraint can be added.")
            return 0

        def _describe(rows, heading):
            if not rows:
                return
            print(heading)
            for profile, reason in rows:
                counts = _linked_record_counts(db, profile)
                shares = len(groups[normalize_passport_number(profile.passport_number)])
                print(f"  profile {profile.id:<6} hpid {profile.hpid or '-':<26} "
                      f"{(profile.full_name or '-')[:24]:<24} "
                      f"passport {str(profile.passport_number)[:16]:<16} — {reason}")
                print(f"      shared with {shares - 1} other account(s); "
                      f"{counts['assignments']} assignment(s), {counts['passes']} pass(es), "
                      f"{counts['bookings']} booking(s) keep pointing at this HPID")
            print()

        _describe(placeholders, "Placeholders — these will be cleared:")
        _describe(maybe_typos, "Possibly a real passport typed wrongly — left "
                               "alone unless --all-invalid:")

        if maybe_typos and not args.all_invalid:
            print("Ask those crew for their passport and correct it, rather "
                  "than clearing the only clue to what it should say.\n")

        print("The HPID is left alone in every case — it is what those "
              "records were written against.")

        if not targets:
            print("\nNo placeholders to clear.")
            return 0

        if not args.apply:
            print(f"\nDry run. Re-run with --apply to clear {len(targets)} "
                  f"passport value(s) to NULL.")
            return 0

        for profile, _ in targets:
            profile.passport_number = None
        db.commit()
        print(f"\nCleared {len(targets)} passport value(s).")

        remaining = defaultdict(int)
        for profile in db.query(CrewProfile).all():
            key = normalize_passport_number(profile.passport_number)
            if key:
                remaining[key] += 1
        still_colliding = sum(1 for count in remaining.values() if count > 1)
        if still_colliding:
            print(f"WARNING: {still_colliding} passport value(s) are still "
                  f"shared. The unique constraint would fail; re-run the audit.")
            return 1
        print("No passport value is shared any more. The unique constraint "
              "can now be added.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
