import unittest
from types import SimpleNamespace
import uuid

import app.db.base  # noqa: F401
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1.routes_ports import PortRulesIn, RuleItem, update_port_rules
from app.db.models.agent_profile import AgentProfile
from app.db.models.port import Port
from app.db.models.port_rule import PortRule
from app.db.models.user import User
from app.db.session import engine


class AgentPortRulePermissionTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)
        suffix = uuid.uuid4().hex[:8]
        self.port = Port(name=f"Test Harbour {suffix}", code=f"port_test_{suffix}", is_active=True)
        self.other = Port(name=f"Other Harbour {suffix}", code=f"port_other_{suffix}", is_active=True)
        self.user = User(email=f"agent-{suffix}@example.com", hashed_password="x", role="agent")
        self.db.add_all([self.port, self.other, self.user])
        self.db.flush()
        self.profile = AgentProfile(
            user_id=self.user.id, agency_name="Test Agency", location="Port",
            assigned_port=self.port.code,
        )
        self.db.add(self.profile)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def test_agent_cannot_write_hidden_configuration(self):
        with self.assertRaises(HTTPException) as error:
            update_port_rules(
                self.port.code, PortRulesIn(timezone="UTC"), self.db, self.user,
            )
        self.assertEqual(error.exception.status_code, 403)

    def test_agent_cannot_write_another_port(self):
        with self.assertRaises(HTTPException) as error:
            update_port_rules(
                self.other.code,
                PortRulesIn(rules=[RuleItem(title="Rule", description="Text", icon_type="policy")]),
                self.db, self.user,
            )
        self.assertEqual(error.exception.status_code, 404)

    def test_multiline_rule_and_verified_number_round_trip(self):
        result = update_port_rules(
            self.port.name,
            PortRulesIn(
                rules=[RuleItem(title="Gate pass", description="Line one\n\nLine two", icon_type="policy")],
                helpline_number="+91 891 234 5678",
            ),
            self.db, self.user,
        )
        self.assertEqual(result["rules"][0]["description"], "Line one\n\nLine two")
        # The contact number is the agency's, so it lands on the agent profile
        # rather than on the shared, superadmin-owned port row.
        self.assertEqual(self.user.agent_profile.support_number, "+91 891 234 5678")

    def test_known_placeholder_number_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            update_port_rules(
                self.port.code,
                PortRulesIn(helpline_number="+91 1800-HEYPORTS"),
                self.db, self.user,
            )
        self.assertEqual(error.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()


class AgentSupportNumberIsolationTests(unittest.TestCase):
    """An agent's contact number is their agency's, not the port's.

    The agent editor wrote straight onto port_rules.helpline_number, the row the
    superadmin owns and every agency at that port shares, so one agent saving
    their number replaced the port helpline for all of them.
    """

    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)

        self.rule = PortRule(port_name="port_isolation_test",
                             helpline_number="+91 1800 PORT", rules=[])
        self.db.add(self.rule)
        self.db.flush()

        self.agent_a = self.make_agent()
        self.agent_b = self.make_agent()

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def make_agent(self):
        user = User(email=f"agent-{uuid.uuid4().hex[:8]}@example.com",
                    hashed_password="x", role="agent")
        self.db.add(user)
        self.db.flush()
        profile = AgentProfile(user_id=user.id, agency_name="Agency",
                               location="Visakhapatnam",
                               assigned_port="port_isolation_test")
        self.db.add(profile)
        self.db.flush()
        return SimpleNamespace(id=user.id, role="agent", agent_profile=profile)

    def save_number(self, agent, number):
        return update_port_rules(
            port_name="port_isolation_test",
            body=PortRulesIn(helpline_number=number),
            db=self.db, current_user=agent,
        )

    def test_the_shared_port_helpline_is_untouched(self):
        self.save_number(self.agent_a, "+91 90000 11111")

        self.db.refresh(self.rule)
        self.assertEqual(self.rule.helpline_number, "+91 1800 PORT")

    def test_the_number_lands_on_the_agency_profile(self):
        self.save_number(self.agent_a, "+91 90000 11111")

        self.assertEqual(self.agent_a.agent_profile.support_number, "+91 90000 11111")

    def test_one_agency_cannot_change_anothers_number(self):
        self.save_number(self.agent_a, "+91 90000 11111")
        self.save_number(self.agent_b, "+91 90000 22222")

        self.assertEqual(self.agent_a.agent_profile.support_number, "+91 90000 11111")
        self.assertEqual(self.agent_b.agent_profile.support_number, "+91 90000 22222")
