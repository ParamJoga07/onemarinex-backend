"""Three faults from the 20.08 agency report.

1. A vessel assigned to an agency from either superadmin screen did not appear
   on that agency's dashboard, while the same vessel added from the agent's own
   screen did. The superadmin form sends an agency name and no agent id, and the
   handler fell back to the superadmin's own id whenever the name failed to
   resolve — so the vessel was created, reported as created, and belonged to
   nobody who could see it.

2. A returning vessel's dashboard card counted the previous call's open safety
   records. The trips beside them were already call-scoped and these were not,
   which is why the card read 1 while the Incidents tab under it read 0.

3. A returning vessel reported the crew of the call before it. The manifest is
   cleared on return, and total_crew falls back to the cached count when there
   is no roster — a number nobody had reset.

Runs against the configured database inside a transaction that is rolled back.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
import uuid

import app.db.base  # noqa: F401 — registers every model on Base
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1.routes_agents import get_dashboard_data
from app.api.v1.routes_superadmin import _agent_for_new_vessel
from app.api.v1.routes_vessels import _start_return_call
from app.db.models.agent_profile import AgentProfile
from app.db.models.crew_sos import CrewSos
from app.db.models.incident import Incident, IncidentStatus, IncidentType
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall
from app.db.models.vessel_crew import VesselCrew
from app.db.session import engine


NOW = datetime.now(timezone.utc)


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class _Base(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)

        self.superadmin_user = User(
            email=_uniq("super") + "@example.com", hashed_password="x",
            role="superadmin")
        self.db.add(self.superadmin_user)
        self.db.flush()
        self.superadmin = SimpleNamespace(
            id=self.superadmin_user.id, role="superadmin", agent_profile=None)

        self.agent_user = User(email=_uniq("agent") + "@example.com",
                               hashed_password="x", role="agent")
        self.db.add(self.agent_user)
        self.db.flush()
        self.agency_name = _uniq("K.Ramabrahmam & Sons Pvt.Ltd")
        self.profile = AgentProfile(
            user_id=self.agent_user.id, agency_name=self.agency_name,
            location="Port", assigned_port="port_test")
        self.db.add(self.profile)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def body(self, **kw):
        base = dict(name=_uniq("MV"), imo_number=_uniq("IMO"),
                    vessel_type="Bulk Carrier", berth_assignment=None,
                    flag="India", agency_name=None, agent_id=None,
                    eta=NOW, etd=NOW + timedelta(days=2))
        base.update(kw)
        return SimpleNamespace(**base)


class SuperadminVesselAssignmentTests(_Base):
    def test_naming_the_agency_assigns_the_vessel_to_that_agency(self):
        chosen = _agent_for_new_vessel(
            self.db, self.body(agency_name=self.agency_name), self.superadmin)
        self.assertEqual(chosen, self.agent_user.id)
        self.assertNotEqual(chosen, self.superadmin_user.id)

    def test_spacing_and_case_do_not_lose_the_agency(self):
        """The old exact match sent these to the superadmin without a word."""
        for variant in (f"  {self.agency_name}  ", self.agency_name.upper(),
                        self.agency_name.lower()):
            chosen = _agent_for_new_vessel(
                self.db, self.body(agency_name=variant), self.superadmin)
            self.assertEqual(chosen, self.agent_user.id, variant)

    def test_an_explicit_agent_id_wins(self):
        chosen = _agent_for_new_vessel(
            self.db, self.body(agent_id=self.agent_user.id), self.superadmin)
        self.assertEqual(chosen, self.agent_user.id)

    def test_other_still_rests_with_the_superadmin(self):
        for value in ("Other", "others", None, ""):
            chosen = _agent_for_new_vessel(
                self.db, self.body(agency_name=value), self.superadmin)
            self.assertEqual(chosen, self.superadmin_user.id, value)

    def test_an_unknown_agency_is_refused_rather_than_quietly_kept(self):
        with self.assertRaises(HTTPException) as caught:
            _agent_for_new_vessel(
                self.db, self.body(agency_name="No Such Agency Ltd"),
                self.superadmin)
        self.assertEqual(caught.exception.status_code, 422)

    def test_two_agencies_of_one_name_are_refused(self):
        other_user = User(email=_uniq("agent2") + "@example.com",
                          hashed_password="x", role="agent")
        self.db.add(other_user)
        self.db.flush()
        self.db.add(AgentProfile(
            user_id=other_user.id, agency_name=self.agency_name,
            location="Port", assigned_port="port_test"))
        self.db.flush()

        with self.assertRaises(HTTPException) as caught:
            _agent_for_new_vessel(
                self.db, self.body(agency_name=self.agency_name),
                self.superadmin)
        self.assertEqual(caught.exception.status_code, 409)


class ReturningVesselTests(_Base):
    def vessel(self):
        v = Vessel(
            agent_id=self.agent_user.id, name=_uniq("MV JIM MING"),
            imo_number=_uniq("IMO"), vessel_type="Bulk Carrier",
            status="Departed", agency_name=self.agency_name,
            eta=NOW - timedelta(days=10), etd=NOW - timedelta(days=8))
        self.db.add(v)
        self.db.flush()
        return v

    def call(self, vessel, *, ended):
        c = VesselCall(
            vessel_id=vessel.id, agency_id=self.profile.id,
            vessel_name=vessel.name, imo_number=vessel.imo_number,
            port_name="port_test", status="DEPARTED" if ended else "ACTIVE",
            eta=vessel.eta, etd=vessel.etd,
            started_at=vessel.eta, ended_at=vessel.etd if ended else None)
        self.db.add(c)
        self.db.flush()
        return c

    def manifest(self, vessel, count):
        for i in range(count):
            self.db.add(VesselCrew(
                vessel_id=vessel.id, name=f"Crew {i}", rank="able_seaman",
                nationality="IN", passport_number=_uniq("P")[:20]))
        self.db.flush()

    def test_the_crew_of_the_previous_call_does_not_follow_the_ship_back(self):
        vessel = self.vessel()
        self.call(vessel, ended=True)
        self.manifest(vessel, 23)
        vessel.crew_count = 23
        self.db.flush()
        self.assertEqual(vessel.total_crew, 23)

        _start_return_call(
            self.db, vessel,
            self.body(name=vessel.name, imo_number=vessel.imo_number),
            agent_id=self.agent_user.id, agency_name=self.agency_name)

        self.db.refresh(vessel)
        self.assertEqual(vessel.crew_count, 0)
        self.assertEqual(vessel.total_crew, 0)

    def test_the_card_counts_this_calls_safety_records_only(self):
        vessel = self.vessel()
        previous = self.call(vessel, ended=True)
        vessel.status = "Active"
        vessel.eta = NOW - timedelta(days=1)
        vessel.etd = NOW + timedelta(days=2)
        self.db.flush()
        current = self.call(vessel, ended=False)

        # One open incident and one open SOS, both on the call that has ended.
        self.db.add(Incident(
            incident_id=_uniq("INC"), type=IncidentType.CREW, title="Old call",
            description="x", status=IncidentStatus.ACTIVE,
            vessel_id=vessel.id, vessel_call_id=previous.id,
            agency_id=self.profile.id, created_at=NOW - timedelta(days=9)))
        self.db.add(CrewSos(
            agency_id=self.profile.id, vessel_id=vessel.id,
            vessel_call_id=previous.id, vessel=vessel.name,
            port_name="port_test", status="ACTIVE",
            created_at=NOW - timedelta(days=9)))
        self.db.flush()

        agent = SimpleNamespace(id=self.agent_user.id, role="agent",
                                agent_profile=self.profile)
        data = get_dashboard_data(db=self.db, current_user=agent)
        card = next(v for v in data.active_vessels if v.id == vessel.id)
        self.assertEqual(card.incidents_count, 0)

        # The same two records on the call the ship is actually on do count.
        self.db.add(Incident(
            incident_id=_uniq("INC"), type=IncidentType.CREW, title="This call",
            description="x", status=IncidentStatus.ACTIVE,
            vessel_id=vessel.id, vessel_call_id=current.id,
            agency_id=self.profile.id, created_at=NOW - timedelta(hours=6)))
        self.db.flush()
        data = get_dashboard_data(db=self.db, current_user=agent)
        card = next(v for v in data.active_vessels if v.id == vessel.id)
        self.assertEqual(card.incidents_count, 1)


if __name__ == "__main__":
    unittest.main()
