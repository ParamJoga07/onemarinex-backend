"""The vessel list a crew member picks from.

It offers every vessel the platform knows, whatever its port and whether or not
it has sailed. Filtering it to the caller's port and to ships still alongside
was doing authorisation's job badly: crew could not find their vessel if an
agent had not onboarded it yet, or if it had just departed, and were left with
nothing to select.

Choosing a vessel grants nothing. The shore leave card and every booking
resolve through the crew assignment, so the list can be honest about what
exists and let that decide.

Archived is the one exclusion — it means removed from operations, not sailed.

Each vessel carries its port and status so the caller can label them, which is
also what tells two ships sharing a name apart.

Runs against the configured database inside a transaction that is always
rolled back.
"""

from datetime import datetime, timedelta, timezone
import unittest
import uuid

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy.orm import Session
from types import SimpleNamespace

from app.db.models.agent_profile import AgentProfile
from app.db.models.port import Port
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall
from app.db.session import engine


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


NOW = datetime.now(timezone.utc)


class PublicVesselListingTests(unittest.TestCase):
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
        )
        self.db.add(self.profile)
        self.db.flush()
        self.agent_user = user
        self.viewer = SimpleNamespace(id=user.id, role="crew")

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def port(self):
        """A port, returning it after the insert hook has set its code."""
        port = Port(name=f"Port of {uuid.uuid4().hex[:8]}", code="ignored")
        self.db.add(port)
        self.db.flush()
        return port

    def vessel_at(self, port, *, name=None, etd=None):
        vessel = Vessel(
            agent_id=self.agent_user.id, name=name or _uniq("MV"),
            imo_number=_uniq("IMO"), vessel_type="Bulk Carrier",
            status="Active", agency_name=self.profile.agency_name,
            eta=NOW - timedelta(days=1), etd=etd or NOW + timedelta(days=5),
        )
        self.db.add(vessel)
        self.db.flush()
        if port is not None:
            self.db.add(VesselCall(
                vessel_id=vessel.id, agency_id=self.profile.id,
                vessel_name=vessel.name, imo_number=vessel.imo_number,
                port_id=port.id, port_name=port.code, status="ACTIVE",
            ))
            self.db.flush()
        return vessel

    def listing(self):
        from app.api.v1.routes_vessels import get_public_vessels

        return get_public_vessels(current_user=self.viewer, db=self.db)

    def test_vessels_in_every_port_are_offered(self):
        """A crew member may be standing on a ship at any of them."""
        here, elsewhere = self.port(), self.port()
        mine = self.vessel_at(here)
        theirs = self.vessel_at(elsewhere)

        offered = {v.id for v in self.listing()}

        self.assertIn(mine.id, offered)
        self.assertIn(theirs.id, offered)

    def test_a_departed_vessel_is_still_offered(self):
        """Crew arrive after the paperwork says the ship has gone.

        Hiding it left them selecting nothing at all, which is worse than
        selecting a ship whose status the list shows them.
        """
        gone = self.vessel_at(self.port(), etd=NOW - timedelta(days=1))

        row = next(v for v in self.listing() if v.id == gone.id)

        self.assertEqual(row.status, "Departed")

    def test_an_archived_vessel_is_not_offered(self):
        """Archived means taken out of operations, which is not the same."""
        archived = self.vessel_at(self.port())
        archived.status = "Archived"
        self.db.flush()

        self.assertNotIn(archived.id, {v.id for v in self.listing()})

    def test_a_vessel_with_no_agent_is_offered(self):
        """The reported defect: only agent-onboarded vessels were visible."""
        unclaimed = self.vessel_at(self.port())
        unclaimed.agent_id = None
        self.db.flush()

        self.assertIn(unclaimed.id, {v.id for v in self.listing()})

    def test_the_port_is_reported_alongside_each_vessel(self):
        """Crew pick by name, so the caller needs this to tell ships apart."""
        here = self.port()
        vessel = self.vessel_at(here)

        row = next(v for v in self.listing() if v.id == vessel.id)

        self.assertEqual(row.port_code, here.code)
        self.assertEqual(row.port_name, here.name)

    def test_two_ships_sharing_a_name_are_distinguishable_by_port(self):
        """The list no longer separates them, so it has to label them."""
        here, elsewhere = self.port(), self.port()
        shared = _uniq("MV")
        self.vessel_at(here, name=shared)
        self.vessel_at(elsewhere, name=shared)

        offered = [v for v in self.listing() if v.name == shared]

        self.assertEqual(len(offered), 2)
        self.assertNotEqual(offered[0].port_code, offered[1].port_code)


if __name__ == "__main__":
    unittest.main()
