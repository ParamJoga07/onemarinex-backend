"""SOS alerts belong to the agent whose ship the crew member sails on.

All three SOS endpoints previously scoped by **port**, so every agency berthed
at the same port could list, view, acknowledge and close each other's
emergencies. SOS is the most sensitive thing in the product: a wrong agent
closing an alert makes it look handled when nobody has gone.

Runs against the configured database inside a transaction that is always rolled
back, so it leaves no rows behind.
"""

import unittest
import uuid
from types import SimpleNamespace

import app.db.base  # noqa: F401 — registers every model on Base
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1.routes_sos import (
    SosCustomUpdateIn,
    SosStatusUpdateIn,
    add_sos_update,
    get_sos_timeline,
    list_sos_requests,
    update_sos_status,
)
from app.db.models.crew_profile import CrewProfile
from app.db.models.crew_sos import CrewSos, CrewSosTimelineEvent
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew
from app.db.session import engine


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class SosVesselScopingTests(unittest.TestCase):
    #  Both agencies sit at the same port — that is the whole point.
    PORT = "port_shared_harbour"

    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)
        self.agent_a, self.sos_a = self.make_agency_with_sos()
        self.agent_b, self.sos_b = self.make_agency_with_sos()

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def make_agency_with_sos(self):
        agent_user = User(email=_uniq("agent") + "@example.com", hashed_password="x", role="agent")
        crew_user = User(email=_uniq("crew") + "@example.com", hashed_password="x", role="crew")
        self.db.add_all([agent_user, crew_user])
        self.db.flush()

        hpid = _uniq("HP")
        crew = CrewProfile(user_id=crew_user.id, full_name="Crew", rank="able_seaman",
                           nationality="IN", hpid=hpid, current_port=self.PORT)
        vessel = Vessel(agent_id=agent_user.id, name=_uniq("MV"), imo_number=_uniq("IMO"),
                        vessel_type="Bulk Carrier", status="Active")
        self.db.add_all([crew, vessel])
        self.db.flush()
        self.db.add(VesselCrew(vessel_id=vessel.id, name="Crew", rank="able_seaman", hp_id=hpid))

        sos = CrewSos(user_id=crew_user.id, crew_profile_id=crew.id,
                      port_name=self.PORT, vessel=vessel.name, status="ACTIVE")
        self.db.add(sos)
        self.db.flush()

        agent = SimpleNamespace(
            id=agent_user.id, role="agent",
            agent_profile=SimpleNamespace(assigned_port=self.PORT),
        )
        return agent, sos

    def test_agent_lists_only_their_own_crews_alerts(self):
        listed = list_sos_requests(db=self.db, current_user=self.agent_a)

        self.assertEqual([s["id"] for s in listed], [self.sos_a.id])

    def test_agent_cannot_open_another_agencys_alert(self):
        with self.assertRaises(HTTPException) as ctx:
            get_sos_timeline(sos_id=self.sos_b.id, db=self.db, current_user=self.agent_a)

        self.assertEqual(ctx.exception.status_code, 404)

    def test_agent_cannot_close_another_agencys_alert(self):
        """The dangerous one: closing it makes an unhandled emergency look handled."""
        with self.assertRaises(HTTPException) as ctx:
            update_sos_status(
                sos_id=self.sos_b.id,
                body=SosStatusUpdateIn(status="CLOSED"),
                db=self.db, current_user=self.agent_a,
            )

        self.assertEqual(ctx.exception.status_code, 404)
        self.db.refresh(self.sos_b)
        self.assertEqual(self.sos_b.status, "ACTIVE")
        self.assertIsNone(self.sos_b.closed_at)

    def test_denied_and_missing_are_indistinguishable(self):
        with self.assertRaises(HTTPException) as denied:
            get_sos_timeline(sos_id=self.sos_b.id, db=self.db, current_user=self.agent_a)
        with self.assertRaises(HTTPException) as missing:
            get_sos_timeline(sos_id=10**9, db=self.db, current_user=self.agent_a)

        self.assertEqual(denied.exception.status_code, missing.exception.status_code)
        self.assertEqual(denied.exception.detail, missing.exception.detail)

    def test_agent_can_still_handle_their_own_alert(self):
        result = update_sos_status(
            sos_id=self.sos_a.id,
            body=SosStatusUpdateIn(status="ACKNOWLEDGED"),
            db=self.db, current_user=self.agent_a,
        )

        self.assertEqual(result.status, "ACKNOWLEDGED")
        self.db.refresh(self.sos_a)
        self.assertIsNotNone(self.sos_a.acknowledged_at)

    def test_status_changes_create_one_persisted_timeline_event_and_are_idempotent(self):
        update_sos_status(
            sos_id=self.sos_a.id,
            body=SosStatusUpdateIn(status="ACKNOWLEDGED"),
            db=self.db, current_user=self.agent_a,
        )
        update_sos_status(
            sos_id=self.sos_a.id,
            body=SosStatusUpdateIn(status="ACKNOWLEDGED"),
            db=self.db, current_user=self.agent_a,
        )

        count = self.db.query(CrewSosTimelineEvent).filter(
            CrewSosTimelineEvent.sos_id == self.sos_a.id,
            CrewSosTimelineEvent.event_type == "ACKNOWLEDGED",
        ).count()
        self.assertEqual(count, 1)

    def test_terminal_alert_cannot_be_reopened_or_receive_activity(self):
        update_sos_status(
            sos_id=self.sos_a.id,
            body=SosStatusUpdateIn(status="CLOSED"),
            db=self.db, current_user=self.agent_a,
        )
        with self.assertRaises(HTTPException) as status_error:
            update_sos_status(
                sos_id=self.sos_a.id,
                body=SosStatusUpdateIn(status="ACTIVE"),
                db=self.db, current_user=self.agent_a,
            )
        with self.assertRaises(HTTPException) as update_error:
            add_sos_update(
                sos_id=self.sos_a.id,
                body=SosCustomUpdateIn(label="Late update"),
                db=self.db, current_user=self.agent_a,
            )
        self.assertEqual(status_error.exception.status_code, 409)
        self.assertEqual(update_error.exception.status_code, 409)

    def test_superadmin_still_sees_everything(self):
        superadmin = SimpleNamespace(id=0, role="superadmin", agent_profile=None)

        listed = list_sos_requests(db=self.db, current_user=superadmin)
        ids = {s["id"] for s in listed}

        self.assertIn(self.sos_a.id, ids)
        self.assertIn(self.sos_b.id, ids)


if __name__ == "__main__":
    unittest.main()
