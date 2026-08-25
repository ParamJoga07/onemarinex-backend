"""A passport identifies a person; a name is how someone typed one.

Crew register themselves as "MARIMUTHU" while their agent types "MARIMUTHU S",
and requiring the two to agree meant the manifest row never mapped: no crew
assignment was created, so no shore pass card appeared and nothing else
resolved either. The passport was right all along.

The rest of the evidence still counts — nationality, HPID, and a passport that
matches more than one account are all still conflicts.

Runs against the configured database inside a transaction that is rolled back.
"""

from datetime import datetime, timedelta, timezone
import unittest
import uuid

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy.orm import Session

from app.api.v1.routes_crew import sync_crew_manifest_helper
from app.db.models.agent_profile import AgentProfile
from app.db.models.crew_assignment import CrewAssignment
from app.db.models.crew_profile import CrewProfile
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall
from app.db.models.vessel_crew import VesselCrew
from app.db.session import engine
from app.services.crew_identity import CrewIdentityConflict, resolve_verified_crew_profile


NOW = datetime.now(timezone.utc)


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _passport():
    return f"S{uuid.uuid4().hex[:7].upper()}"


class _Base(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)

        agent_user = User(email=_uniq("agent") + "@example.com",
                          hashed_password="x", role="agent")
        self.db.add(agent_user)
        self.db.flush()
        self.agency = AgentProfile(
            user_id=agent_user.id, agency_name=_uniq("Agency"),
            location="Port", assigned_port="port_test")
        self.db.add(self.agency)
        self.db.flush()
        self.agent_user = agent_user

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def profile(self, *, name, passport, nationality="IN"):
        user = User(email=_uniq("crew") + "@example.com",
                    hashed_password="x", role="crew")
        self.db.add(user)
        self.db.flush()
        p = CrewProfile(user_id=user.id, full_name=name, rank="third_officer",
                        nationality=nationality, passport_number=passport,
                        hpid=_uniq("HP"))
        self.db.add(p)
        self.db.flush()
        return p


class ProfileResolutionTests(_Base):
    def test_a_different_spelling_still_resolves_the_account(self):
        passport = _passport()
        profile = self.profile(name="MARIMUTHU", passport=passport)
        for typed in ("MARIMUTHU S", "S MARIMUTHU", "Mari Muthu", "marimuthu"):
            got = resolve_verified_crew_profile(
                self.db, passport_number=passport, nationality="IN",
                crew_name=typed)
            self.assertIsNotNone(got, typed)
            self.assertEqual(got.id, profile.id, typed)

    def test_nationality_is_still_evidence(self):
        passport = _passport()
        self.profile(name="MARIMUTHU", passport=passport, nationality="IN")
        with self.assertRaises(CrewIdentityConflict) as caught:
            resolve_verified_crew_profile(
                self.db, passport_number=passport, nationality="PH",
                crew_name="MARIMUTHU")
        self.assertIn("different nationality", str(caught.exception))

    def test_one_passport_on_two_accounts_is_still_a_conflict(self):
        passport = _passport()
        self.profile(name="One Person", passport=passport)
        self.profile(name="Another Person", passport=passport)
        with self.assertRaises(CrewIdentityConflict):
            resolve_verified_crew_profile(
                self.db, passport_number=passport, nationality="IN",
                crew_name="One Person")


class ShorePassAppearsTests(_Base):
    """The end the crew member actually sees."""

    def vessel_with_manifest_row(self, *, crew_name, passport):
        vessel = Vessel(
            agent_id=self.agent_user.id, name=_uniq("MV"),
            imo_number=_uniq("IMO"), vessel_type="Bulk Carrier",
            status="Active", agency_name=self.agency.agency_name,
            eta=NOW - timedelta(days=1), etd=NOW + timedelta(days=2))
        self.db.add(vessel)
        self.db.flush()
        self.db.add(VesselCall(
            vessel_id=vessel.id, agency_id=self.agency.id,
            vessel_name=vessel.name, imo_number=vessel.imo_number,
            port_name="port_test", status="ACTIVE", eta=vessel.eta,
            etd=vessel.etd, started_at=vessel.eta, ended_at=None))
        row = VesselCrew(
            vessel_id=vessel.id, name=crew_name, rank="third_officer",
            nationality="IN", passport_number=passport, status="Pending",
            shore_pass_eligible=True)
        self.db.add(row)
        self.db.flush()
        return vessel, row

    def test_the_agents_spelling_no_longer_keeps_crew_off_their_vessel(self):
        passport = _passport()
        # The agent typed the name one way on the manifest...
        _vessel, row = self.vessel_with_manifest_row(
            crew_name="MARIMUTHU S", passport=passport)
        # ...and the crew member registered under another.
        profile = self.profile(name="MARIMUTHU", passport=passport)

        sync_crew_manifest_helper(profile, self.db)
        self.db.flush()

        self.db.refresh(row)
        self.assertEqual(row.status, "Mapped")
        assignment = self.db.query(CrewAssignment).filter(
            CrewAssignment.vessel_crew_id == row.id).first()
        self.assertIsNotNone(assignment, "no assignment means no shore pass card")
        self.assertEqual(assignment.crew_profile_id, profile.id)
        self.assertTrue(assignment.shore_pass_eligible)


if __name__ == "__main__":
    unittest.main()
