import unittest
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
        self.assertEqual(result["helpline_number"], "+91 891 234 5678")

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
