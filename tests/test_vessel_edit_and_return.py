"""Editing a vessel, and a vessel that comes back to port.

Two behaviours that both hinge on when a port call may be opened or closed.

Editing must never do either. The superadmin edit used to infer `agent_id` from
the submitted agency name — a field the form resubmits whether or not it
changed — and then read the change as a reassignment: it finished the current
call and opened a new one. Correcting an ETD started a fresh port call. On an
archived vessel it was worse: archiving nulls `agent_id`, so the condition
always fired, and since a call cannot be manufactured for a departed vessel the
old one was closed with nothing opened in its place.

Adding a vessel whose IMO is already known is the opposite case. That is a
return visit, and it *should* open a new call — against the same vessel record,
never a second one.

Runs against the configured database inside a transaction that is always
rolled back.
"""

from datetime import datetime, timedelta, timezone
import unittest
import uuid

import app.db.base  # noqa: F401 — registers every model on Base
from fastapi import HTTPException
from sqlalchemy.orm import Session
from types import SimpleNamespace

from app.db.models.agent_profile import AgentProfile
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall
from app.db.session import engine


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


NOW = datetime.now(timezone.utc)


class _Base(unittest.TestCase):
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
        self.agent_user = user
        self.agent = SimpleNamespace(id=user.id, role="agent",
                                     agent_profile=self.profile)
        self.superadmin = SimpleNamespace(id=user.id, role="superadmin",
                                          agent_profile=None)

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def vessel(self, *, imo=None, status="Active", agent=True):
        v = Vessel(
            agent_id=self.agent_user.id if agent else None,
            name=_uniq("MV"), imo_number=imo or _uniq("IMO"),
            vessel_type="Bulk Carrier", status=status,
            agency_name=self.profile.agency_name,
            eta=NOW - timedelta(days=2), etd=NOW + timedelta(days=2),
        )
        self.db.add(v)
        self.db.flush()
        return v

    def call_for(self, vessel, *, ended=False, etd=None):
        # A real call carries the voyage dates, and `finish_vessel_call` stamps
        # ended_at *from* the ETD — so a departed call has the two equal. The
        # fixture used to leave etd null, which quietly exempted it from the
        # reopen path and made these tests agree with production by accident.
        call_etd = etd or vessel.etd or (NOW - timedelta(days=1))
        call = VesselCall(
            vessel_id=vessel.id, agency_id=self.profile.id,
            vessel_name=vessel.name, imo_number=vessel.imo_number,
            port_name="port_test", status="DEPARTED" if ended else "ACTIVE",
            eta=vessel.eta, etd=call_etd,
            ended_at=call_etd if ended else None,
        )
        self.db.add(call)
        self.db.flush()
        return call

    def calls(self, vessel):
        return self.db.query(VesselCall).filter(
            VesselCall.vessel_id == vessel.id).all()

    def open_calls(self, vessel):
        return [c for c in self.calls(vessel) if c.ended_at is None]


class VesselEditTests(_Base):
    def _edit(self, vessel, **overrides):
        from app.api.v1.routes_superadmin import (
            SuperAdminVesselCreate, update_vessel_superadmin,
        )
        payload = dict(
            name=vessel.name, imo_number=vessel.imo_number,
            vessel_type=vessel.vessel_type,
            berth_assignment=vessel.berth_assignment, flag=vessel.flag,
            agency_name=self.profile.agency_name,
            eta=vessel.eta, etd=vessel.etd,
        )
        payload.update(overrides)
        return update_vessel_superadmin(
            vessel_id=vessel.id, body=SuperAdminVesselCreate(**payload),
            db=self.db, current_user=self.superadmin,
        )

    def test_changing_the_etd_does_not_start_a_new_call(self):
        """The reported defect."""
        vessel = self.vessel()
        self.call_for(vessel)

        self._edit(vessel, etd=NOW + timedelta(days=9))

        self.assertEqual(len(self.calls(vessel)), 1)
        self.assertEqual(len(self.open_calls(vessel)), 1)

    def test_the_open_call_picks_up_the_new_etd(self):
        vessel = self.vessel()
        call = self.call_for(vessel)
        wanted = NOW + timedelta(days=9)

        self._edit(vessel, etd=wanted)

        self.db.refresh(call)
        self.assertEqual(call.etd.replace(microsecond=0), wanted.replace(microsecond=0))

    def test_editing_an_archived_vessel_leaves_its_history_alone(self):
        """Archiving nulls agent_id, which used to guarantee the bug fired.

        The old call was closed and no new one could be opened for a departed
        vessel, so the vessel was left with no call at all.
        """
        vessel = self.vessel(status="Archived", agent=False)
        ended = self.call_for(vessel, ended=True)

        self._edit(vessel, name="Renamed In History")

        self.db.refresh(ended)
        self.assertEqual(len(self.calls(vessel)), 1)
        self.assertEqual(len(self.open_calls(vessel)), 0)
        self.assertEqual(ended.status, "DEPARTED")

    def test_editing_a_departed_vessel_does_not_reopen_it(self):
        vessel = self.vessel(status="Departed", agent=False)
        self.call_for(vessel, ended=True)

        self._edit(vessel, etd=NOW + timedelta(days=5))

        self.assertEqual(len(self.open_calls(vessel)), 0)

    def test_extending_a_departed_vessels_etd_reopens_the_same_call(self):
        """The ship never left; the estimate expired.

        Status is derived from ETD, so a date in the past departs the vessel and
        the sync closes its call. Pushing that date forward says the departure
        did not happen — the agent is extending the stay, not recording a new
        voyage. Leaving the call closed stranded the vessel as Active with no
        call at all, and crew, trips and reports all hang off the call.

        Reopening is not the defect this file was written for. That one opened a
        *second* call, which arrived carrying a duplicate of the crew roster;
        the assertion on the total count below is what guards it.
        """
        vessel = self.vessel(status="Departed", agent=True)
        call = self.call_for(vessel, ended=True)

        self._edit(vessel, etd=NOW + timedelta(days=12))

        self.assertEqual(len(self.calls(vessel)), 1)
        self.assertEqual([c.id for c in self.open_calls(vessel)], [call.id])

    def test_reopening_carries_the_new_etd_onto_the_call(self):
        vessel = self.vessel(status="Departed", agent=True)
        call = self.call_for(vessel, ended=True)
        wanted = NOW + timedelta(days=12)

        self._edit(vessel, etd=wanted)

        self.db.refresh(call)
        self.assertIsNone(call.ended_at)
        self.assertEqual(call.etd.replace(microsecond=0), wanted.replace(microsecond=0))

    def test_a_call_ended_by_hand_is_not_reopened_by_an_etd_edit(self):
        """Only a departure the clock caused is undone by moving the clock.

        A call finished deliberately — or archived, or reassigned — records a
        ship that actually sailed. Its end does not coincide with its ETD, and
        correcting a date must not resurrect it.
        """
        vessel = self.vessel(status="Departed", agent=True)
        call = self.call_for(vessel, ended=True)
        call.ended_at = NOW - timedelta(days=3)
        self.db.flush()

        self._edit(vessel, etd=NOW + timedelta(days=12))

        self.assertEqual(len(self.open_calls(vessel)), 0)

    def test_an_archived_call_is_never_reopened(self):
        vessel = self.vessel(status="Departed", agent=True)
        call = self.call_for(vessel, ended=True)
        call.status = "ARCHIVED"
        self.db.flush()

        self._edit(vessel, etd=NOW + timedelta(days=12))

        self.assertEqual(len(self.open_calls(vessel)), 0)

    def test_a_vessel_still_in_port_keeps_its_call_when_the_etd_moves(self):
        """Extending a live call must not close or duplicate it."""
        vessel = self.vessel(status="Active")
        call = self.call_for(vessel)

        self._edit(vessel, etd=NOW + timedelta(days=6))

        self.assertEqual([c.id for c in self.open_calls(vessel)], [call.id])


class ReturningVesselTests(_Base):
    def _add(self, *, imo, name=None, etd=None):
        from app.api.v1.routes_vessels import VesselIn, create_vessel
        return create_vessel(
            body=VesselIn(
                name=name or _uniq("MV"), imo_number=imo,
                vessel_type="Bulk Carrier", berth_assignment="B2", flag="Panama",
                agency_name=self.profile.agency_name,
                eta=NOW + timedelta(days=1),
                etd=etd or NOW + timedelta(days=4),
            ),
            current_user=self.agent, db=self.db,
        )

    def test_a_returning_vessel_reuses_its_record_and_opens_a_new_call(self):
        """Item 8: same vessel id, new call id."""
        first = self.vessel(status="Departed", agent=False)
        self.call_for(first, ended=True)
        imo = first.imo_number

        returned = self._add(imo=imo)

        self.assertEqual(returned.id, first.id)
        self.assertEqual(len(self.calls(first)), 2)
        self.assertEqual(len(self.open_calls(first)), 1)

    def test_the_new_call_carries_the_new_voyage_dates(self):
        first = self.vessel(status="Departed", agent=False)
        self.call_for(first, ended=True)
        wanted = NOW + timedelta(days=11)

        self._add(imo=first.imo_number, etd=wanted)

        open_call = self.open_calls(first)[0]
        self.assertEqual(open_call.etd.replace(microsecond=0), wanted.replace(microsecond=0))

    def test_the_earlier_call_is_untouched(self):
        """Past calls and their reports must not move."""
        first = self.vessel(status="Departed", agent=False)
        ended = self.call_for(first, ended=True)
        was_ended_at, was_status = ended.ended_at, ended.status

        self._add(imo=first.imo_number)

        self.db.refresh(ended)
        self.assertEqual(ended.ended_at, was_ended_at)
        self.assertEqual(ended.status, was_status)

    def test_an_imo_with_an_open_call_is_refused_with_the_details(self):
        """Two live calls for one hull would split its crew and trips."""
        vessel = self.vessel()
        self.call_for(vessel)

        with self.assertRaises(HTTPException) as ctx:
            self._add(imo=vessel.imo_number)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn(vessel.imo_number, ctx.exception.detail)
        self.assertIn("already has an open", ctx.exception.detail)
        self.assertEqual(len(self.open_calls(vessel)), 1)

    def test_the_imo_is_matched_despite_spacing_and_prefix(self):
        """Agents type it by hand: "9617741", "IMO 9617741", " 9617741 "."""
        number = str(9000000 + int(uuid.uuid4().int % 999999))
        first = self.vessel(imo=number, status="Departed", agent=False)
        self.call_for(first, ended=True)

        returned = self._add(imo=f"  imo {number} ")

        self.assertEqual(returned.id, first.id)

    def test_an_identifier_merely_beginning_with_imo_is_not_mangled(self):
        """Stripping the three letters unconditionally corrupted these."""
        first = self.vessel(imo="IMOSPECIAL-4471", status="Departed", agent=False)
        self.call_for(first, ended=True)

        returned = self._add(imo="imospecial-4471")

        self.assertEqual(returned.id, first.id)

    def _add_as_superadmin(self, *, imo, name=None):
        from app.api.v1.routes_superadmin import (
            SuperAdminVesselCreate, create_vessel_superadmin,
        )
        return create_vessel_superadmin(
            body=SuperAdminVesselCreate(
                name=name or _uniq("MV"), imo_number=imo,
                vessel_type="Bulk Carrier", berth_assignment="B2", flag="Panama",
                agency_name=self.profile.agency_name,
                eta=NOW + timedelta(days=1), etd=NOW + timedelta(days=4),
            ),
            db=self.db, current_user=self.superadmin,
        )

    def test_superadmin_re_adding_a_known_imo_reuses_the_vessel(self):
        """The reported defect: "Vessel IMO possibly already exists".

        The agent path has reused the canonical vessel since this file was
        written. Superadmin still built a second row, so the unique index
        rejected it and the handler reported a message that named no vessel and
        offered no next step.
        """
        first = self.vessel(status="Departed", agent=False)
        self.call_for(first, ended=True)

        returned = self._add_as_superadmin(imo=first.imo_number)

        self.assertEqual(returned.id, first.id)
        self.assertEqual(len(self.calls(first)), 2)
        self.assertEqual(len(self.open_calls(first)), 1)

    def test_superadmin_is_refused_an_imo_that_is_still_in_port(self):
        vessel = self.vessel()
        self.call_for(vessel)

        with self.assertRaises(HTTPException) as ctx:
            self._add_as_superadmin(imo=vessel.imo_number)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("already has an open", ctx.exception.detail)

    def test_a_genuinely_new_imo_still_creates_a_vessel(self):
        before = self.db.query(Vessel).count()

        created = self._add(imo=_uniq("IMO"))

        self.assertEqual(self.db.query(Vessel).count(), before + 1)
        self.assertEqual(len(self.open_calls(created)), 1)


if __name__ == "__main__":
    unittest.main()
