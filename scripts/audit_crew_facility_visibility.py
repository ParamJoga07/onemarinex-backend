"""Why a facility category is empty for crew but present for the superadmin.

The crew screens and the superadmin list the same `vendors` table through
different filters, so a vendor can be perfectly visible in one and absent from
the other. Three things differ, and each hides a vendor silently:

  * **status** — every crew endpoint requires exactly `Active`
  * **category** — pubs match `ILIKE 'pub'`, which is case-insensitive but still
    an exact word: `Pubs` or `Pub & Bar` do not match. Massage and wellness use
    an `IN (...)` list, which is case-*sensitive*, so `Massage` does not match
  * **port_id** — the crew screens resolve it from their current port and send
    it; a vendor on another port, or with none, drops out

This prints what each crew endpoint would return, then the vendors it rejected
and the reason, so the difference is visible rather than inferred.

Read-only.

Usage (from onemarinex-backend/):
    PYTHONPATH=. python scripts/audit_crew_facility_visibility.py
    PYTHONPATH=. python scripts/audit_crew_facility_visibility.py --port 1
"""
import argparse
import sys
from collections import defaultdict

from types import SimpleNamespace

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy import func

from app.db.session import SessionLocal
from app.db.models.vendors import Vendors
from app.services.vendor_ranking import vendor_category_text

# What each crew screen actually asks for, copied from the routes so a drift
# between them shows up here rather than in front of a crew member.
CREW_FILTERS = {
    "Pubs": ("ilike", ["pub"]),
    "Restaurants": ("ilike", ["restaurant"]),
    "Massage & Wellness": ("in", ["massage", "wellness"]),
    "Shopping & Utility": ("in", ["shopping", "utility"]),
}


def _crew_endpoints():
    """The functions the crew screens actually call.

    Imported inside the function so this script still reports the stored data
    even if one of the route modules cannot be imported.
    """
    from app.api.v1.routes_facilities import (
        get_massage_wellness, get_shopping_utility,
    )
    from app.api.v1.routes_pubs import get_pubs

    return (
        ("Pubs", lambda db, user, port: get_pubs(
            port_id=port, db=db, current_user=user)),
        ("Massage & Wellness", lambda db, user, port: get_massage_wellness(
            port_id=port, db=db, current_user=user)),
        ("Shopping & Utility", lambda db, user, port: get_shopping_utility(
            port_id=port, db=db, current_user=user)),
    )


def _blame_the_vendor(db, label, port_id):
    """Name the row the response model refuses, and why.

    One bad vendor takes the whole list down with it, so the useful answer is
    which one — not that the category is broken.
    """
    mode, wanted = CREW_FILTERS[label]
    query = db.query(Vendors).filter(Vendors.status == "Active")
    if mode == "ilike":
        query = query.filter(vendor_category_text().ilike(wanted[0]))
    else:
        query = query.filter(vendor_category_text().in_(wanted))
    if port_id is not None:
        query = query.filter(Vendors.port_id == port_id)

    from app.api.v1.routes_facilities import _vendor_to_facility

    blamed = 0
    for vendor in query.all():
        try:
            _vendor_to_facility(vendor)
        except Exception as exc:  # noqa: BLE001
            blamed += 1
            print(f"      vendor {vendor.id:<5} "
                  f"{(vendor.name or '-')[:32]:<32} {type(exc).__name__}")
            for line in str(exc).splitlines()[:6]:
                print(f"          {line.strip()}")
    if not blamed:
        print("      No single vendor fails on its own — the failure is in the "
              "endpoint itself rather than one row.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, help="port_id the crew would send")
    parser.add_argument("--crew", help="a crew email: resolve their port the way "
                                       "their own screens do, and report what "
                                       "they would actually see")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.crew:
            # Replay the resolution the crew screens perform: read the profile,
            # take current_port, and match it against ports.code. A mismatch
            # there sends no port_id at all, which quietly widens the list
            # rather than narrowing it — worth seeing plainly.
            from app.db.models.crew_profile import CrewProfile
            from app.db.models.port import Port
            from app.db.models.user import User

            user = db.query(User).filter(
                func.lower(User.email) == args.crew.strip().lower()).first()
            profile = db.query(CrewProfile).filter(
                CrewProfile.user_id == user.id).first() if user else None
            if profile is None:
                print(f"No crew profile for {args.crew!r}.")
                return 1
            port = db.query(Port).filter(Port.code == profile.current_port).first()
            print(f"{args.crew}")
            print(f"  current_port on the profile : {profile.current_port!r}")
            print(f"  matches ports.code          : "
                  f"{'yes, port_id ' + str(port.id) if port else 'NO MATCH'}")
            if port is None:
                print("  -> the screens send no port_id, so no port filter is "
                      "applied and every active vendor is returned.")
            args.port = port.id if port else None
            print()

        print("Every vendor, as stored:\n")
        rows = (
            db.query(Vendors.category, Vendors.status, Vendors.port_id,
                     func.count(Vendors.id))
            .group_by(Vendors.category, Vendors.status, Vendors.port_id)
            .order_by(Vendors.category)
            .all()
        )
        for category, status, port_id, count in rows:
            print(f"  {str(category):<16} {str(status):<10} port {str(port_id):<6} {count}")

        print(f"\n{'=' * 74}")
        # Call the endpoints themselves rather than re-implementing their
        # filters. A query returning rows proves nothing if the response model
        # then refuses one of them: the endpoint 500s, the screen shows its
        # empty state, and a database-level audit reports everything is fine.
        viewer = SimpleNamespace(id=0, role="crew")
        for label, call in _crew_endpoints():
            try:
                rows = call(db, viewer, args.port)
            except Exception as exc:  # noqa: BLE001 — seeing it is the point
                print(f"\n{label}: the endpoint FAILED — {type(exc).__name__}")
                print(f"    {str(exc).splitlines()[0]}")
                print("    A crew member sees the empty state for this. The "
                      "vendor responsible:")
                _blame_the_vendor(db, label, args.port)
                continue
            print(f"\n{label}: crew would see {len(rows)}")

        print(f"\n{'=' * 74}")
        if args.port is None:
            print("Re-run with --port <id> to apply the port filter the crew "
                  "screens send, which is resolved from their current port.")
        print("Read-only. Nothing written.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
