"""A vendor's working days must not take its whole category off the screen.

Pubs and Massage & Wellness went blank for crew while the superadmin still
listed them. The filters were not the cause — the same query returns four of
each at the port in question. The response model was: `working_days` was
declared a string, and the vendor form stores the seven-day array that fixing
"the vendor form rejects all seven working days" introduced.

One vendor holding a list made the whole response fail validation, so the
endpoint 500'd and the screen showed "No pubs found in this area" — an empty
state standing in for an error, which is why it read as missing data.

Restaurants and sightseeing were unaffected because they return untyped dicts
and never validate. That is the only reason those two kept working.

Runs against the configured database inside a transaction that is always
rolled back.
"""

from types import SimpleNamespace
import unittest
import uuid

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy.orm import Session

from app.api.v1.routes_facilities import _vendor_to_facility
from app.api.v1.routes_pubs import get_pubs
from app.db.models.vendors import Vendors
from app.db.session import engine


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class WorkingDaysListingTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)
        self.viewer = SimpleNamespace(id=0, role="crew")

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def vendor(self, category, working_days):
        row = Vendors(
            name=_uniq("Venue"), category=category, status="Active",
            location_name="Somewhere", distance_from_port=1.0, rating=4.0,
            lat=0.0, lng=0.0, phone="+910000000000",
            email=_uniq("venue") + "@example.com", commission_percentage=0,
            other_information={"working_days": working_days},
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _pub(self, working_days):
        row = self.vendor("pub", working_days)
        found = [r for r in get_pubs(port_id=None, db=self.db,
                                     current_user=self.viewer) if r.id == row.id]
        self.assertEqual(len(found), 1, "the vendor fell out of the listing")
        return found[0]

    def test_the_seven_day_array_does_not_break_the_listing(self):
        """The reported defect, in the shape the vendor form now stores."""
        row = self._pub(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

        self.assertEqual(len(row.working_days), 7)

    def test_one_bad_vendor_does_not_hide_the_others(self):
        """A whole category went blank because of a single row."""
        self.vendor("pub", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        healthy = self.vendor("pub", None)

        listed = {r.id for r in get_pubs(port_id=None, db=self.db,
                                         current_user=self.viewer)}

        self.assertIn(healthy.id, listed)

    def test_a_legacy_comma_separated_value_still_reads(self):
        """Older rows hold a CSV string and must not start failing instead."""
        self.assertEqual(self._pub("Mon,Tue,Wed").working_days,
                         ["Mon", "Tue", "Wed"])

    def test_a_json_string_reads_as_days_not_characters(self):
        self.assertEqual(self._pub('["Mon","Tue"]').working_days, ["Mon", "Tue"])

    def test_no_working_days_is_still_allowed(self):
        self.assertIsNone(self._pub(None).working_days)

    def test_the_facility_model_is_fixed_the_same_way(self):
        """Massage & Wellness serialises through FacilityOut, not PubOut.

        Exercised through the serialiser rather than the endpoint because this
        database still types `category` as an enum without a `massage` member —
        production widened it to a VARCHAR, which is why the code casts. The
        declaration is the thing under test either way.
        """
        row = self.vendor("pub", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])

        facility = _vendor_to_facility(row)

        self.assertEqual(len(facility.working_days), 7)


if __name__ == "__main__":
    unittest.main()
