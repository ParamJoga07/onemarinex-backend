"""Crew real-time activity mirrors the driver's magic link, for the agent.

The magic link itself is public — anyone holding the unguessable token can see
a trip's progress. The agent-facing equivalent is addressed by booking id, which
is far more guessable, so it must be scoped to the agent's own crew.

Runs against the configured database inside a transaction that is always rolled
back, so it leaves no rows behind.
"""

import unittest
import uuid
from types import SimpleNamespace

import app.db.base  # noqa: F401 — registers every model on Base
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1.routes_trips import get_trip_activity
from app.db.models.cab_booking import BookingStatus, CabBooking
from app.db.models.crew_profile import CrewProfile
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew
from app.db.session import engine


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class TripActivityScopingTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)
        self.agent_a, self.booking_a = self.make_agent_with_trip()
        self.agent_b, self.booking_b = self.make_agent_with_trip()

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def make_agent_with_trip(self):
        agent = User(email=_uniq("agent") + "@example.com", hashed_password="x", role="agent")
        crew_user = User(email=_uniq("crew") + "@example.com", hashed_password="x", role="crew")
        self.db.add_all([agent, crew_user])
        self.db.flush()

        hpid = _uniq("HP")
        crew = CrewProfile(user_id=crew_user.id, full_name="Crew", rank="able_seaman",
                           nationality="IN", hpid=hpid)
        vessel = Vessel(agent_id=agent.id, name=_uniq("MV"), imo_number=_uniq("IMO"),
                        vessel_type="Bulk Carrier", status="Active")
        self.db.add_all([crew, vessel])
        self.db.flush()
        self.db.add(VesselCrew(vessel_id=vessel.id, name="Crew", rank="able_seaman", hp_id=hpid))

        booking = CabBooking(
            booking_id=_uniq("CAB"), crew_id=crew.id,
            pickup_address="Gate", pickup_lat=0, pickup_lng=0,
            drop_address="City", drop_lat=0, drop_lng=0,
            vehicle_type="ac", vehicle_name="Sedan", estimated_price=100,
            distance_km=5, status=BookingStatus.ON_TRIP,
            driver_name="Ramesh", driver_phone="+910000000000", driver_plate="AP39 AB 1234",
        )
        self.db.add(booking)
        self.db.flush()

        return SimpleNamespace(id=agent.id, role="agent", agent_profile=None), booking

    def activity(self, agent, booking_id):
        return get_trip_activity(booking_id=booking_id, db=self.db, current_user=agent)

    def test_agent_sees_activity_for_their_own_trip(self):
        result = self.activity(self.agent_a, self.booking_a.booking_id)

        self.assertEqual(result.booking_id, self.booking_a.booking_id)
        self.assertEqual(result.driver_name, "Ramesh")

    def test_no_driver_link_yet_reports_tracking_unavailable(self):
        """The trip exists but nothing is being tracked — say so plainly."""
        result = self.activity(self.agent_a, self.booking_a.booking_id)

        self.assertFalse(result.tracking_available)
        self.assertEqual(result.stops_total, 0)

    def test_another_agents_trip_is_not_readable(self):
        with self.assertRaises(HTTPException) as ctx:
            self.activity(self.agent_a, self.booking_b.booking_id)

        self.assertEqual(ctx.exception.status_code, 404)

    def test_another_agents_trip_is_indistinguishable_from_a_missing_one(self):
        """Otherwise an agent could probe for other agencies' booking ids."""
        with self.assertRaises(HTTPException) as denied:
            self.activity(self.agent_a, self.booking_b.booking_id)
        with self.assertRaises(HTTPException) as missing:
            self.activity(self.agent_a, "CAB-DOES-NOT-EXIST")

        self.assertEqual(denied.exception.status_code, missing.exception.status_code)
        self.assertEqual(denied.exception.detail, missing.exception.detail)

    def test_non_agents_are_refused(self):
        crew = SimpleNamespace(id=self.agent_a.id, role="crew", agent_profile=None)

        with self.assertRaises(HTTPException) as ctx:
            self.activity(crew, self.booking_a.booking_id)

        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
