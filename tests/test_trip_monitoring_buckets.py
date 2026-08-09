"""Trip Monitoring must bucket trips by where the driver actually is.

The agent's Trips screen has three tabs, and the spec ties them to the driver's
own actions:

    requested  from the trip being raised until the driver reaches pickup
    on going   from the driver reaching pickup until the ride is completed
    completed  once the driver marks the ride complete

Previously `arrived` and `on_trip` appeared in no bucket at all, so a ride that
was genuinely underway vanished from every tab, and `driver_assigned` /
`driver_accepted` were shown as on-going when the driver was still en route.

Runs against the configured database inside a transaction that is always rolled
back, so it leaves no rows behind.
"""

import unittest
import uuid
from types import SimpleNamespace

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy.orm import Session

from app.api.v1.routes_trips import get_trip_monitoring
from app.db.models.cab_booking import BookingStatus, CabBooking
from app.db.models.crew_profile import CrewProfile
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew
from app.db.session import engine


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class TripMonitoringBucketTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)

        agent = User(email=_uniq("agent") + "@example.com", hashed_password="x", role="agent")
        crew_user = User(email=_uniq("crew") + "@example.com", hashed_password="x", role="crew")
        self.db.add_all([agent, crew_user])
        self.db.flush()

        hpid = _uniq("HP")
        self.crew = CrewProfile(
            user_id=crew_user.id, full_name="Test Crew", rank="AB", nationality="IN", hpid=hpid
        )
        vessel = Vessel(
            agent_id=agent.id, name=_uniq("MV"), imo_number=_uniq("IMO"),
            vessel_type="Bulk Carrier", status="Active",
        )
        self.db.add_all([self.crew, vessel])
        self.db.flush()
        self.db.add(VesselCrew(vessel_id=vessel.id, name="Test Crew", rank="AB", hp_id=hpid))
        self.db.flush()

        self.agent_user = SimpleNamespace(id=agent.id, role="agent", agent_profile=None)

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def add_trip(self, status):
        self.db.add(CabBooking(
            booking_id=_uniq("CAB"), crew_id=self.crew.id,
            pickup_address="Gate", pickup_lat=0, pickup_lng=0,
            drop_address="City", drop_lat=0, drop_lng=0,
            vehicle_type="ac", vehicle_name="Sedan", estimated_price=100,
            distance_km=5, status=status,
        ))
        self.db.flush()

    def buckets(self):
        r = get_trip_monitoring(db=self.db, current_user=self.agent_user)
        return {"ongoing": len(r.ongoing), "requested": len(r.requested), "completed": len(r.completed)}

    def test_driver_en_route_counts_as_requested_not_ongoing(self):
        self.add_trip(BookingStatus.DRIVER_ASSIGNED)
        self.add_trip(BookingStatus.DRIVER_ACCEPTED)

        self.assertEqual(self.buckets(), {"ongoing": 0, "requested": 2, "completed": 0})

    def test_arrived_and_on_trip_are_ongoing(self):
        # These previously matched no bucket and disappeared from the screen.
        self.add_trip(BookingStatus.ARRIVED)
        self.add_trip(BookingStatus.ON_TRIP)

        self.assertEqual(self.buckets(), {"ongoing": 2, "requested": 0, "completed": 0})

    def test_legacy_in_progress_still_counts_as_ongoing(self):
        self.add_trip(BookingStatus.IN_PROGRESS)

        self.assertEqual(self.buckets()["ongoing"], 1)

    def test_pending_states_are_requested(self):
        self.add_trip(BookingStatus.PENDING_PROVIDER_RESPONSE)
        self.add_trip(BookingStatus.PROVIDER_ACCEPTED)

        self.assertEqual(self.buckets(), {"ongoing": 0, "requested": 2, "completed": 0})

    def test_completed_is_completed(self):
        self.add_trip(BookingStatus.COMPLETED)

        self.assertEqual(self.buckets(), {"ongoing": 0, "requested": 0, "completed": 1})

    def test_cancelled_trips_are_not_shown(self):
        self.add_trip(BookingStatus.CANCELLED)
        self.add_trip(BookingStatus.PROVIDER_REJECTED)

        self.assertEqual(self.buckets(), {"ongoing": 0, "requested": 0, "completed": 0})

    def test_no_live_trip_is_ever_dropped(self):
        """The regression that started this: every live status must appear somewhere."""
        live = [
            BookingStatus.PENDING_PROVIDER_RESPONSE,
            BookingStatus.PROVIDER_ACCEPTED,
            BookingStatus.DRIVER_ASSIGNED,
            BookingStatus.DRIVER_ACCEPTED,
            BookingStatus.ARRIVED,
            BookingStatus.ON_TRIP,
        ]
        for s in live:
            self.add_trip(s)

        counts = self.buckets()
        self.assertEqual(
            counts["ongoing"] + counts["requested"] + counts["completed"],
            len(live),
            f"a live trip is missing from every tab: {counts}",
        )


if __name__ == "__main__":
    unittest.main()
