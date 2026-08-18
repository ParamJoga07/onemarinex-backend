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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, help="port_id the crew would send")
    args = parser.parse_args()

    db = SessionLocal()
    try:
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
        for label, (mode, wanted) in CREW_FILTERS.items():
            query = db.query(Vendors)
            if mode == "ilike":
                query = query.filter(vendor_category_text().ilike(wanted[0]))
            else:
                query = query.filter(vendor_category_text().in_(wanted))
            matching_category = query.all()

            active = [v for v in matching_category if v.status == "Active"]
            visible = active
            if args.port is not None:
                visible = [v for v in active if v.port_id == args.port]

            print(f"\n{label}: crew would see {len(visible)}")
            if len(matching_category) != len(active):
                for vendor in matching_category:
                    if vendor.status != "Active":
                        print(f"    hidden: {vendor.name[:34]:<34} "
                              f"status is {vendor.status!r}, not 'Active'")
            if args.port is not None:
                for vendor in active:
                    if vendor.port_id != args.port:
                        print(f"    hidden: {vendor.name[:34]:<34} "
                              f"is on port {vendor.port_id}, not {args.port}")

            # Anything whose category looks like this one but does not match the
            # filter — the case and wording traps.
            near = []
            for vendor in db.query(Vendors).all():
                text = str(vendor.category or "")
                if vendor in matching_category:
                    continue
                if any(word in text.lower() for word in wanted):
                    near.append(vendor)
            for vendor in near:
                reason = ("category is case-sensitive here"
                          if mode == "in" else "category must be the exact word")
                print(f"    MISSED: {vendor.name[:34]:<34} "
                      f"category {str(vendor.category)!r} — {reason}")

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
