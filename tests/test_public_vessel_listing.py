"""The vessel list a crew member picks from after choosing their port.

`port_code` was accepted by the endpoint and never read, so choosing a port
changed nothing: crew were offered every active vessel in every port. A vessel
row carries no port of its own — the port belongs to the open call — which is
why the filter could not be a plain column comparison and was left unbuilt.

That mattered twice over, because the selection is resolved by vessel *name*.
Two ships sharing a name in different ports were indistinguishable in the list,
and the first one listed won.

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

    def listing(self, port_code=None):
        from app.api.v1.routes_vessels import get_public_vessels

        return get_public_vessels(
            port_code=port_code, current_user=self.viewer, db=self.db,
        )

    def test_only_vessels_in_the_requested_port_are_offered(self):
        """The reported defect: the port choice did nothing."""
        here, elsewhere = self.port(), self.port()
        mine = self.vessel_at(here)
        theirs = self.vessel_at(elsewhere)

        offered = {v.id for v in self.listing(port_code=here.code)}

        self.assertIn(mine.id, offered)
        self.assertNotIn(theirs.id, offered)

    def test_an_unfiltered_request_still_offers_every_port(self):
        """Callers that never sent a port must keep working."""
        here, elsewhere = self.port(), self.port()
        mine = self.vessel_at(here)
        theirs = self.vessel_at(elsewhere)

        offered = {v.id for v in self.listing()}

        self.assertIn(mine.id, offered)
        self.assertIn(theirs.id, offered)

    def test_a_vessel_with_no_open_call_is_not_in_any_port(self):
        """Nothing places it, so it belongs to nobody's port list."""
        here = self.port()
        unplaced = self.vessel_at(None)

        offered = {v.id for v in self.listing(port_code=here.code)}

        self.assertNotIn(unplaced.id, offered)

    def test_the_port_is_reported_alongside_each_vessel(self):
        """Crew pick by name, so the caller needs this to tell ships apart."""
        here = self.port()
        vessel = self.vessel_at(here)

        row = next(v for v in self.listing(port_code=here.code)
                   if v.id == vessel.id)

        self.assertEqual(row.port_code, here.code)
        self.assertEqual(row.port_name, here.name)

    def test_two_ships_sharing_a_name_are_split_by_port(self):
        """The collision the name-keyed dropdown could not survive."""
        here, elsewhere = self.port(), self.port()
        shared = _uniq("MV")
        mine = self.vessel_at(here, name=shared)
        self.vessel_at(elsewhere, name=shared)

        offered = [v for v in self.listing(port_code=here.code)
                   if v.name == shared]

        self.assertEqual([v.id for v in offered], [mine.id])

    def test_a_departed_vessel_is_not_offered(self):
        """Existing behaviour: status is derived from ETD."""
        here = self.port()
        gone = self.vessel_at(here, etd=NOW - timedelta(days=1))

        offered = {v.id for v in self.listing(port_code=here.code)}

        self.assertNotIn(gone.id, offered)


if __name__ == "__main__":
    unittest.main()
