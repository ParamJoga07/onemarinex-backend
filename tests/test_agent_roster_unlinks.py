"""Agent roster removals unlink associations without deleting shared data."""

import unittest
import uuid
from datetime import datetime

import app.db.base  # noqa: F401
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1.routes_vessels import (
    get_crew_profile,
    unlink_crew_from_vessel,
    unlink_vessel_from_agent,
)
from app.api.v1.routes_agents import get_dashboard_data
from app.api.v1.routes_incidents import agent_safety_report_records
from app.db.models.agent_roster_event import AgentRosterEvent
from app.db.models.cab_booking import BookingStatus, CabBooking
from app.db.models.crew_profile import CrewProfile
from app.db.models.incident import Incident, IncidentType
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew
from app.db.session import engine


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class AgentRosterUnlinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        AgentRosterEvent.__table__.create(bind=engine, checkfirst=True)

    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        self.db = Session(bind=self.connection)

        self.agent = User(
            email=_uniq("agent") + "@example.com", hashed_password="x", role="agent"
        )
        self.other_agent = User(
            email=_uniq("other") + "@example.com", hashed_password="x", role="agent"
        )
        crew_user = User(
            email=_uniq("crew") + "@example.com", hashed_password="x", role="crew"
        )
        self.db.add_all([self.agent, self.other_agent, crew_user])
        self.db.flush()

        self.profile = CrewProfile(
            user_id=crew_user.id,
            full_name="Preserved Crew",
            rank="able_seaman",
            nationality="IN",
            hpid=_uniq("HP"),
        )
        self.vessel = Vessel(
            agent_id=self.agent.id,
            name=_uniq("MV"),
            imo_number=_uniq("IMO"),
            vessel_type="Bulk Carrier",
        )
        self.db.add_all([self.profile, self.vessel])
        self.db.flush()
        self.manifest = VesselCrew(
            vessel_id=self.vessel.id,
            name="Preserved Crew",
            rank="able_seaman",
            hp_id=self.profile.hpid,
        )
        self.incident = Incident(
            incident_id=_uniq("INC"),
            type=IncidentType.CREW,
            title="Existing history",
            description="Must survive unlink",
            reporter_id=self.profile.hpid,
            vessel_id=self.vessel.id,
        )
        self.db.add_all([self.manifest, self.incident])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def test_crew_unlink_preserves_account_and_incident_history(self):
        result = unlink_crew_from_vessel(
            vessel_id=self.vessel.id,
            crew_id=self.manifest.id,
            current_user=self.agent,
            db=self.db,
        )

        self.assertEqual(result.action, "crew_unlinked")
        self.assertIsNone(
            self.db.query(VesselCrew).filter(VesselCrew.id == self.manifest.id).first()
        )
        self.assertIsNotNone(
            self.db.query(CrewProfile).filter(CrewProfile.id == self.profile.id).first()
        )
        self.assertIsNotNone(
            self.db.query(Incident).filter(Incident.id == self.incident.id).first()
        )
        event = self.db.query(AgentRosterEvent).filter(
            AgentRosterEvent.crew_manifest_id == self.manifest.id
        ).one()
        self.assertEqual(event.actor_user_id, self.agent.id)
        self.assertEqual(event.subject_hpid, self.profile.hpid)

    def test_agent_cannot_unlink_another_agents_crew(self):
        with self.assertRaises(HTTPException) as ctx:
            unlink_crew_from_vessel(
                vessel_id=self.vessel.id,
                crew_id=self.manifest.id,
                current_user=self.other_agent,
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_vessel_unlink_keeps_the_canonical_record(self):
        vessel_id = self.vessel.id
        result = unlink_vessel_from_agent(
            vessel_id=vessel_id, current_user=self.agent, db=self.db
        )

        self.assertEqual(result.action, "vessel_unlinked")
        canonical = self.db.query(Vessel).filter(Vessel.id == vessel_id).one()
        self.assertIsNone(canonical.agent_id)
        self.assertIsNotNone(
            self.db.query(Incident).filter(Incident.id == self.incident.id).first()
        )
        self.assertEqual(
            self.db.query(AgentRosterEvent).filter(
                AgentRosterEvent.vessel_id == vessel_id,
                AgentRosterEvent.action == "VESSEL_UNLINKED",
            ).count(),
            1,
        )
        dashboard = get_dashboard_data(db=self.db, current_user=self.agent)
        self.assertEqual(dashboard.stats.total_vessels, 0)
        self.assertEqual(dashboard.active_vessels, [])
        with self.assertRaises(HTTPException) as report_error:
            agent_safety_report_records(
                vessel_id=vessel_id, db=self.db, current_user=self.agent
            )
        self.assertEqual(report_error.exception.status_code, 404)

    def test_agent_cannot_unlink_another_agents_vessel(self):
        self.vessel.agent_id = self.other_agent.id
        self.db.flush()

        with self.assertRaises(HTTPException) as error:
            unlink_vessel_from_agent(
                vessel_id=self.vessel.id, current_user=self.agent, db=self.db
            )

        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(self.vessel.agent_id, self.other_agent.id)

    def test_crew_profile_is_scoped_and_bookings_are_newest_first(self):
        created = datetime.utcnow()
        for suffix in ("A", "B"):
            self.db.add(CabBooking(
                booking_id=_uniq(f"CAB-{suffix}"),
                crew_id=self.profile.id,
                pickup_address="Gate",
                pickup_lat=17.7,
                pickup_lng=83.3,
                drop_address="City",
                drop_lat=17.71,
                drop_lng=83.31,
                vehicle_type="ac",
                vehicle_name="Sedan",
                estimated_price=100,
                distance_km=5,
                status=BookingStatus.COMPLETED,
                created_at=created,
            ))
        self.db.flush()

        result = get_crew_profile(
            hp_id=self.profile.hpid, current_user=self.agent, db=self.db
        )
        booking_ids = [booking.id for booking in result["bookings"]]
        self.assertEqual(booking_ids, sorted(booking_ids, reverse=True))

        with self.assertRaises(HTTPException) as denied:
            get_crew_profile(
                hp_id=self.profile.hpid,
                current_user=self.other_agent,
                db=self.db,
            )
        with self.assertRaises(HTTPException) as missing:
            get_crew_profile(
                hp_id="HP-NOT-FOUND",
                current_user=self.other_agent,
                db=self.db,
            )
        self.assertEqual(denied.exception.status_code, 404)
        self.assertEqual(denied.exception.detail, missing.exception.detail)


if __name__ == "__main__":
    unittest.main()
