"""Moving an SOS alert back to the ship it names.

Seven production alerts name MT. BABYLON or MV COMMON LUCK and display as
MV JIM MING 82. The live SOS path cannot produce that — it takes the call and
the vessel name from one `event_context` result — so they came from the
l3m4n5o6p7q8 backfill, which joined bookings to calls on vessel_id alone with
no time window and let an arbitrary call win.

The repair trusts the alert's own `vessel` text, the event-time snapshot the
backfill never touched, and moves the alert to the call of that name whose port
time contains it. Anything less certain than exactly one such call is left for
a person.

Runs against the configured database inside a transaction that is rolled back.
"""

from datetime import datetime, timedelta, timezone
import unittest
import uuid

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy.orm import Session

from app.db.models.agent_profile import AgentProfile
from app.db.models.crew_assignment import CrewAssignment
from app.db.models.crew_profile import CrewProfile
from app.db.models.crew_sos import CrewSos
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall
from app.db.session import engine

from scripts.repair_sos_vessel_call import apply_plan, plan


NOW = datetime.now(timezone.utc)


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class RepairSosVesselCallTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)

        user = User(email=_uniq("agent") + "@example.com",
                    hashed_password="x", role="agent")
        self.db.add(user)
        self.db.flush()
        self.profile = AgentProfile(
            user_id=user.id, agency_name=_uniq("Agency"), location="Port",
            assigned_port="port_test",
        )
        self.db.add(self.profile)
        self.db.flush()

        crew_user = User(email=_uniq("crew") + "@example.com",
                         hashed_password="x", role="crew")
        self.db.add(crew_user)
        self.db.flush()
        self.crew = CrewProfile(
            user_id=crew_user.id, full_name="Test Crew", rank="Third Officer",
            nationality="IN", hpid=_uniq("HP"),
        )
        self.db.add(self.crew)
        self.db.flush()

        # The two ships of the production case, named so the comparison has to
        # cope with the punctuation a person writes.
        self.babylon = self._vessel("MT. BABYLON")
        self.jim_ming = self._vessel("MV JIM MING 82")

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def _vessel(self, name):
        v = Vessel(
            agent_id=self.profile.user_id, name=name, imo_number=_uniq("IMO"),
            vessel_type="Tanker", status="Active",
            agency_name=self.profile.agency_name,
            eta=NOW - timedelta(days=10), etd=NOW + timedelta(days=2),
        )
        self.db.add(v)
        self.db.flush()
        return v

    def _call(self, vessel, *, start, end, name=None):
        call = VesselCall(
            vessel_id=vessel.id, agency_id=self.profile.id,
            vessel_name=name or vessel.name, imo_number=vessel.imo_number,
            port_name="port_test", status="DEPARTED" if end else "ACTIVE",
            eta=start, etd=end or NOW + timedelta(days=2),
            started_at=start, ended_at=end,
        )
        self.db.add(call)
        self.db.flush()
        return call

    def _sos(self, *, names, stamped_with, created):
        sos = CrewSos(
            crew_profile_id=self.crew.id, agency_id=self.profile.id,
            vessel_id=stamped_with.vessel_id, vessel_call_id=stamped_with.id,
            vessel=names, port_name="port_test", status="CLOSED",
            context_resolution="booking", created_at=created,
        )
        self.db.add(sos)
        self.db.flush()
        return sos

    def test_an_alert_moves_to_the_ship_it_names(self):
        moment = NOW - timedelta(days=8)
        babylon_call = self._call(
            self.babylon, start=NOW - timedelta(days=9), end=NOW - timedelta(days=7))
        jim_ming_call = self._call(
            self.jim_ming, start=NOW - timedelta(days=3), end=None)
        # Written with a full stop the call does not have, as production has it.
        sos = self._sos(names="MT. BABYLON", stamped_with=jim_ming_call,
                        created=moment)

        _mismatched, planned, blocked = plan(self.db)
        self.assertEqual(blocked, [])
        self.assertEqual(len(planned), 1)
        apply_plan(self.db, planned)

        self.assertEqual(sos.vessel_call_id, babylon_call.id)
        self.assertEqual(sos.vessel_id, self.babylon.id)
        self.assertEqual(sos.context_resolution, "repaired_vessel_name")

    def test_punctuation_and_case_do_not_make_a_mismatch(self):
        """'MT BABYLON' on the call and 'mt. babylon' on the alert are one ship."""
        call = self._call(self.babylon, start=NOW - timedelta(days=9),
                          end=NOW - timedelta(days=7), name="MT BABYLON")
        self._sos(names="mt. babylon", stamped_with=call,
                  created=NOW - timedelta(days=8))

        mismatched, planned, _blocked = plan(self.db)
        self.assertEqual(mismatched, [])
        self.assertEqual(planned, [])

    def test_an_alert_outside_every_matching_call_is_left_alone(self):
        jim_ming_call = self._call(
            self.jim_ming, start=NOW - timedelta(days=3), end=None)
        self._call(self.babylon, start=NOW - timedelta(days=9),
                   end=NOW - timedelta(days=7))
        # Raised long before that visit: nothing to move it to with confidence.
        sos = self._sos(names="MT. BABYLON", stamped_with=jim_ming_call,
                        created=NOW - timedelta(days=40))

        _mismatched, planned, blocked = plan(self.db)
        self.assertEqual(planned, [])
        self.assertEqual(len(blocked), 1)
        apply_plan(self.db, planned)
        self.assertEqual(sos.vessel_call_id, jim_ming_call.id)

    def test_two_matching_calls_are_left_for_a_person(self):
        jim_ming_call = self._call(
            self.jim_ming, start=NOW - timedelta(days=3), end=None)
        moment = NOW - timedelta(days=8)
        # Two visits by the same ship whose windows both contain the alert.
        self._call(self.babylon, start=NOW - timedelta(days=9),
                   end=NOW - timedelta(days=7))
        self._call(self.babylon, start=NOW - timedelta(days=10),
                   end=NOW - timedelta(days=6))
        sos = self._sos(names="MT. BABYLON", stamped_with=jim_ming_call,
                        created=moment)

        _mismatched, planned, blocked = plan(self.db)
        self.assertEqual(planned, [])
        self.assertEqual(len(blocked), 1)
        self.assertEqual(len(blocked[0][2]), 2)
        apply_plan(self.db, planned)
        self.assertEqual(sos.vessel_call_id, jim_ming_call.id)

    def test_the_assignment_follows_the_call_or_is_dropped(self):
        babylon_call = self._call(
            self.babylon, start=NOW - timedelta(days=9), end=NOW - timedelta(days=7))
        jim_ming_call = self._call(
            self.jim_ming, start=NOW - timedelta(days=3), end=None)
        assignment = CrewAssignment(
            vessel_call_id=babylon_call.id, crew_profile_id=self.crew.id,
            crew_name="Test Crew", rank="Third Officer",
        )
        self.db.add(assignment)
        self.db.flush()
        sos = self._sos(names="MT. BABYLON", stamped_with=jim_ming_call,
                        created=NOW - timedelta(days=8))

        _mismatched, planned, _blocked = plan(self.db)
        apply_plan(self.db, planned)
        self.assertEqual(sos.crew_assignment_id, assignment.id)

    def test_running_it_again_finds_nothing_to_do(self):
        babylon_call = self._call(
            self.babylon, start=NOW - timedelta(days=9), end=NOW - timedelta(days=7))
        jim_ming_call = self._call(
            self.jim_ming, start=NOW - timedelta(days=3), end=None)
        self._sos(names="MT. BABYLON", stamped_with=jim_ming_call,
                  created=NOW - timedelta(days=8))

        _mismatched, planned, _blocked = plan(self.db)
        apply_plan(self.db, planned)
        self.db.flush()

        mismatched_again, planned_again, blocked_again = plan(self.db)
        self.assertEqual(mismatched_again, [])
        self.assertEqual(planned_again, [])
        self.assertEqual(blocked_again, [])
        self.assertTrue(babylon_call.id)


if __name__ == "__main__":
    unittest.main()
