"""The shore-pass expiry is one date for the whole crew, with per-person overrides.

It used to be typed in per crew member on the Add Crew form. It is really a
property of the port call, so it now lives on the vessel and is pushed down to
the manifest.

The behaviour that matters: applying the master date reaches everyone, and an
individual can still be given a different date afterwards without the master
value clobbering it until it is applied again.

Runs against the configured database inside a transaction that is always rolled
back, so it leaves no rows behind.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy.orm import Session

from app.api.v1.routes_vessels import (
    ShorePassValidityIn,
    set_vessel_shore_pass_validity,
)
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew
from app.db.session import engine


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class ShorePassMasterDateTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)

        agent = User(email=_uniq("agent") + "@example.com", hashed_password="x", role="agent")
        self.db.add(agent)
        self.db.flush()
        self.agent = SimpleNamespace(id=agent.id, role="agent", agent_profile=None)

        self.vessel = Vessel(
            agent_id=agent.id, name=_uniq("MV"), imo_number=_uniq("IMO"),
            vessel_type="Bulk Carrier", status="Active",
        )
        self.db.add(self.vessel)
        self.db.flush()

        self.master = datetime(2026, 8, 20, 18, 0, tzinfo=timezone.utc)
        self.other = self.master + timedelta(days=2)

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def add_crew(self, valid_upto=None):
        c = VesselCrew(
            vessel_id=self.vessel.id, name="Crew", rank="able_seaman",
            hp_id=_uniq("HP"), shore_pass_valid_upto=valid_upto,
        )
        self.db.add(c)
        self.db.flush()
        return c

    def apply(self, when, apply_to_all=True):
        return set_vessel_shore_pass_validity(
            vessel_id=self.vessel.id,
            body=ShorePassValidityIn(shore_pass_valid_upto=when, apply_to_all=apply_to_all),
            current_user=self.agent,
            db=self.db,
        )

    def dates(self, *crew):
        for c in crew:
            self.db.refresh(c)
        return [c.shore_pass_valid_upto for c in crew]

    def test_master_date_reaches_every_crew_member(self):
        a, b, c = self.add_crew(), self.add_crew(), self.add_crew()

        result = self.apply(self.master)

        self.assertEqual(result.crew_updated, 3)
        self.assertEqual(self.dates(a, b, c), [self.master] * 3)

    def test_master_date_is_stored_on_the_vessel(self):
        self.apply(self.master)

        self.db.refresh(self.vessel)
        self.assertEqual(self.vessel.shore_pass_valid_upto, self.master)

    def test_an_individual_can_be_given_a_different_date_afterwards(self):
        a, b = self.add_crew(), self.add_crew()
        self.apply(self.master)

        # The per-crew endpoint writes this field directly.
        a.shore_pass_valid_upto = self.other
        self.db.flush()

        self.assertEqual(self.dates(a, b), [self.other, self.master])

    def test_reapplying_the_master_resets_overrides(self):
        """Documented behaviour: applying again is how you get everyone back in line."""
        a = self.add_crew(valid_upto=self.other)

        self.apply(self.master)

        self.assertEqual(self.dates(a), [self.master])

    def test_apply_to_all_false_leaves_existing_dates_alone(self):
        overridden = self.add_crew(valid_upto=self.other)
        blank = self.add_crew()

        result = self.apply(self.master, apply_to_all=False)

        self.assertEqual(result.crew_updated, 1)
        self.assertEqual(self.dates(overridden, blank), [self.other, self.master])

    def test_clearing_the_master_clears_the_crew(self):
        a = self.add_crew(valid_upto=self.other)

        self.apply(None)

        self.assertEqual(self.dates(a), [None])

    def test_another_agents_vessel_is_not_reachable(self):
        intruder = SimpleNamespace(id=self.agent.id + 99999, role="agent", agent_profile=None)

        with self.assertRaises(Exception) as ctx:
            set_vessel_shore_pass_validity(
                vessel_id=self.vessel.id,
                body=ShorePassValidityIn(shore_pass_valid_upto=self.master),
                current_user=intruder,
                db=self.db,
            )
        self.assertIn("404", str(getattr(ctx.exception, "status_code", "")) or str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
