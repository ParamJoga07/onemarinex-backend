"""Release 2 report snapshots are immutable and agency-scoped."""

from types import SimpleNamespace
import unittest
import uuid

import app.db.base  # noqa: F401
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1.routes_incidents import (
    create_agent_safety_report_snapshot,
    get_agent_safety_report_snapshot,
)
from app.db.models.agent_profile import AgentProfile
from app.db.models.crew_profile import CrewProfile
from app.db.models.incident import Incident, IncidentStatus, IncidentType
from app.db.models.report_snapshot import ReportSnapshot
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew
from app.db.session import engine
from app.services.historical_context import active_vessel_call, assignment_for_manifest
from app.services.report_snapshots import canonical_payload


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class ReportSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        self.db = Session(bind=self.connection)
        self.agent, self.profile, self.incident, self.assignment, self.call = self.make_record()

    def tearDown(self):
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def make_record(self):
        agent_user = User(
            email=_uniq("agent") + "@example.com", hashed_password="x", role="agent"
        )
        crew_user = User(
            email=_uniq("crew") + "@example.com", hashed_password="x", role="crew",
            mobile_number="+91 90000 00000",
        )
        self.db.add_all([agent_user, crew_user])
        self.db.flush()
        agency = AgentProfile(
            user_id=agent_user.id,
            agency_name=_uniq("Agency"),
            location="Test Port",
        )
        crew = CrewProfile(
            user_id=crew_user.id,
            full_name="Current Crew Name",
            rank="current_rank",
            nationality="IN",
            hpid=_uniq("HP"),
        )
        vessel = Vessel(
            agent_id=agent_user.id,
            name="MV EVENT TIME",
            imo_number=_uniq("IMO"),
            vessel_type="Bulk Carrier",
            status="Active",
        )
        self.db.add_all([agency, crew, vessel])
        self.db.flush()
        manifest = VesselCrew(
            vessel_id=vessel.id,
            name="Event Time Crew",
            rank="third_officer",
            nationality="Indian",
            hp_id=crew.hpid,
        )
        self.db.add(manifest)
        self.db.flush()
        call = active_vessel_call(self.db, vessel)
        assignment = assignment_for_manifest(self.db, vessel, manifest, profile=crew)
        incident = Incident(
            incident_id=_uniq("INC"),
            type=IncidentType.CREW,
            title="Original incident",
            description="Original description",
            status=IncidentStatus.RESOLVED,
            reporter_id=crew.hpid,
            crew_profile_id=crew.id,
            crew_assignment_id=assignment.id,
            vessel_id=vessel.id,
            vessel_call_id=call.id,
            agency_id=agency.id,
            context_resolution="assignment",
        )
        self.db.add(incident)
        self.db.flush()
        actor = SimpleNamespace(
            id=agent_user.id,
            role="agent",
            name="Agent",
            agent_profile=agency,
        )
        return actor, agency, incident, assignment, call

    def create_snapshot(self):
        return create_agent_safety_report_snapshot(
            record_kind="incident",
            record_id=self.incident.id,
            db=self.db,
            current_user=self.agent,
        )

    def test_snapshot_uses_event_time_crew_and_vessel_context(self):
        result = self.create_snapshot()

        self.assertEqual(result["payload"]["reporter"]["full_name"], "Event Time Crew")
        self.assertEqual(result["payload"]["reporter"]["rank"], "third_officer")
        self.assertEqual(result["payload"]["vessel"]["name"], "MV EVENT TIME")

    def test_snapshot_does_not_change_with_source_records(self):
        created = self.create_snapshot()
        snapshot_id = created["snapshot_id"]
        original = created["payload"]

        self.assignment.crew_name = "Later Crew Name"
        self.assignment.rank = "captain"
        self.call.vessel_name = "MV LATER NAME"
        self.incident.title = "Rewritten incident"
        self.db.flush()

        stored = get_agent_safety_report_snapshot(
            snapshot_id=snapshot_id, db=self.db, current_user=self.agent
        )
        self.assertEqual(stored["payload"], original)
        _, digest = canonical_payload(original)
        self.assertEqual(stored["payload_sha256"], digest)

    def test_each_generation_is_a_new_audit_artifact(self):
        first = self.create_snapshot()
        self.incident.title = "Later version"
        self.db.flush()
        second = self.create_snapshot()

        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertNotEqual(first["payload_sha256"], second["payload_sha256"])
        self.assertEqual(
            self.db.query(ReportSnapshot).filter(
                ReportSnapshot.report_kind == "incident",
                ReportSnapshot.source_id == self.incident.id,
            ).count(),
            2,
        )

    def test_other_agent_cannot_read_snapshot_but_superadmin_can(self):
        created = self.create_snapshot()
        other, _, _, _, _ = self.make_record()

        with self.assertRaises(HTTPException) as denied:
            get_agent_safety_report_snapshot(
                snapshot_id=created["snapshot_id"], db=self.db, current_user=other
            )
        self.assertEqual(denied.exception.status_code, 404)

        superadmin = SimpleNamespace(id=0, role="superadmin")
        visible = get_agent_safety_report_snapshot(
            snapshot_id=created["snapshot_id"], db=self.db, current_user=superadmin
        )
        self.assertEqual(visible["snapshot_id"], created["snapshot_id"])


if __name__ == "__main__":
    unittest.main()
