"""Crew on a vessel no agency runs are not waiting for anything.

A vessel recorded as "Other" has no agent, so no manifest is ever uploaded and
no crew assignment is ever created. Everything that waits for an assignment
therefore waits forever — which is how cabs stayed locked behind "your shipping
agent adds you to the crew list" on a vessel with no agent to do it, while the
profile beside it already reported cab_booking_locked false.

A partnered vessel with no assignment is the opposite case: a crew member their
agent has not added yet. That is a real wait and stays refused.

Runs against the configured database inside a transaction that is rolled back.
"""

from datetime import datetime, timedelta, timezone
import unittest
import uuid

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy.orm import Session

from app.api.v1.routes_crew import _unmanaged_vessel_call
from app.db.models.agent_profile import AgentProfile
from app.db.models.crew_profile import CrewProfile
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall
from app.db.session import engine


NOW = datetime.now(timezone.utc)


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class UnmanagedVesselTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)

        holder = User(email=_uniq("holder") + "@example.com",
                      hashed_password="x", role="superadmin")
        agent_user = User(email=_uniq("agent") + "@example.com",
                          hashed_password="x", role="agent")
        crew_user = User(email=_uniq("crew") + "@example.com",
                         hashed_password="x", role="crew")
        self.db.add_all([holder, agent_user, crew_user])
        self.db.flush()
        self.holder = holder
        self.agent_user = agent_user

        self.agency = AgentProfile(
            user_id=agent_user.id, agency_name=_uniq("Praveen Shipping"),
            location="Port", assigned_port="port_test")
        self.db.add(self.agency)
        self.db.flush()

        self.profile = CrewProfile(
            user_id=crew_user.id, full_name="Test Crew", rank="third_officer",
            nationality="IN", hpid=_uniq("HP"))
        self.db.add(self.profile)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def vessel(self, *, agency_name, agent_id, with_call=True):
        v = Vessel(
            agent_id=agent_id, name=_uniq("MV"), imo_number=_uniq("IMO"),
            vessel_type="Bulk Carrier", status="Active",
            agency_name=agency_name,
            eta=NOW - timedelta(days=1), etd=NOW + timedelta(days=2))
        self.db.add(v)
        self.db.flush()
        if with_call:
            self.db.add(VesselCall(
                vessel_id=v.id,
                agency_id=None if agency_name == "Other" else self.agency.id,
                vessel_name=v.name, imo_number=v.imo_number,
                port_name="port_test", status="ACTIVE", eta=v.eta, etd=v.etd,
                started_at=v.eta, ended_at=None))
            self.db.flush()
        self.profile.selected_vessel_id = v.id
        self.db.flush()
        return v

    def test_an_other_vessel_resolves_a_call_without_an_assignment(self):
        vessel = self.vessel(agency_name="Other", agent_id=self.holder.id)
        got_vessel, got_call = _unmanaged_vessel_call(self.db, self.profile)
        self.assertIsNotNone(got_vessel)
        self.assertEqual(got_vessel.id, vessel.id)
        self.assertIsNotNone(got_call)
        self.assertEqual(got_call.vessel_id, vessel.id)

    def test_a_partnered_vessel_is_still_a_genuine_wait(self):
        self.vessel(agency_name=self.agency.agency_name,
                    agent_id=self.agent_user.id)
        got_vessel, got_call = _unmanaged_vessel_call(self.db, self.profile)
        self.assertIsNone(got_vessel)
        self.assertIsNone(got_call)

    def test_every_spelling_of_unassigned_counts_as_unmanaged(self):
        for name in ("Other", "others", "None", "N/A", "  other  ", ""):
            self.vessel(agency_name=name, agent_id=self.holder.id)
            got_vessel, _ = _unmanaged_vessel_call(self.db, self.profile)
            self.assertIsNotNone(got_vessel, name)

    def test_no_selected_vessel_resolves_nothing(self):
        self.profile.selected_vessel_id = None
        self.db.flush()
        self.assertEqual(_unmanaged_vessel_call(self.db, self.profile),
                         (None, None))

    def test_an_other_vessel_with_no_open_call_still_refuses(self):
        """Nothing to attach the booking to, so it is not silently invented."""
        self.vessel(agency_name="Other", agent_id=self.holder.id,
                    with_call=False)
        got_vessel, got_call = _unmanaged_vessel_call(self.db, self.profile)
        self.assertIsNotNone(got_vessel)
        self.assertIsNone(got_call)


if __name__ == "__main__":
    unittest.main()
