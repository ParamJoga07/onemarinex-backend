"""Regression coverage for the agent Add Crew identity boundary."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

import app.db.base  # noqa: F401 - register all models
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.v1.routes_vessels import CrewMemberIn, add_crew_member
from app.db.models.agent_profile import AgentProfile
from app.db.models.crew_assignment import CrewAssignment
from app.db.models.crew_identity_conflict import CrewIdentityConflictRecord
from app.db.models.crew_profile import CrewProfile
from app.db.models.shore_pass import ShorePass
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew
from app.db.session import engine
from app.services.crew_identity import normalize_passport_number


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class AddCrewIdentityTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        self.db = Session(bind=self.connection)

        self.agent = User(
            email=f"{_uniq('agent')}@example.com",
            hashed_password="x",
            role="agent",
        )
        self.db.add(self.agent)
        self.db.flush()
        self.db.add(AgentProfile(
            user_id=self.agent.id,
            agency_name="Test Shipping",
            location="Visakhapatnam",
            assigned_port="port_visakhapatnam",
        ))
        self.vessel = Vessel(
            agent_id=self.agent.id,
            name=_uniq("MV IDENTITY"),
            imo_number=_uniq("IMO"),
            vessel_type="Bulk Carrier",
            agency_name="Test Shipping",
            eta=datetime.now(timezone.utc) - timedelta(hours=1),
            etd=datetime.now(timezone.utc) + timedelta(days=2),
            status="Active",
        )
        self.db.add(self.vessel)
        self.db.flush()
        self.db.refresh(self.agent)

    def tearDown(self):
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def body(self, **overrides) -> CrewMemberIn:
        values = {
            "name": "Ravi Kumar",
            "rank": "AB",
            "nationality": "Indian",
            "passport_number": _uniq("P").replace("-", ""),
            "status": "Mapped",
            "shore_pass_eligible": True,
        }
        values.update(overrides)
        return CrewMemberIn(**values)

    def add_profile(self, *, passport: str, nationality: str = "IN", name="Ravi Kumar"):
        user = User(
            email=f"{_uniq('crew')}@example.com",
            hashed_password="x",
            role="crew",
        )
        self.db.add(user)
        self.db.flush()
        profile = CrewProfile(
            user_id=user.id,
            full_name=name,
            rank="able_seaman",
            nationality=nationality,
            passport_number=passport,
            hpid=_uniq("HP-STABLE"),
        )
        self.db.add(profile)
        self.db.flush()
        return profile

    def add(self, body: CrewMemberIn):
        return add_crew_member(
            vessel_id=self.vessel.id,
            body=body,
            current_user=self.agent,
            db=self.db,
        )

    def test_client_cannot_claim_mapped_status_without_an_account(self):
        result = self.add(self.body(status="Mapped"))

        self.assertEqual(result.status, "Pending")

    def test_unique_normalized_passport_maps_to_stable_existing_account(self):
        profile = self.add_profile(passport=" ab 12 34 ")

        result = self.add(self.body(passport_number="AB1234"))

        self.assertEqual(result.status, "Mapped")
        self.assertEqual(result.hp_id, profile.hpid)
        assignment = self.db.query(CrewAssignment).filter(
            CrewAssignment.vessel_crew_id == result.id
        ).one()
        self.assertEqual(assignment.crew_profile_id, profile.id)

    def test_identical_retry_returns_existing_membership_and_shore_pass(self):
        passport = _uniq("R").replace("-", "")
        profile = self.add_profile(passport=passport)
        body = self.body(passport_number=f" {passport.lower()} ")

        first = self.add(body)
        second = self.add(body)

        self.assertEqual(second.id, first.id)
        self.assertEqual(
            self.db.query(VesselCrew).filter(VesselCrew.vessel_id == self.vessel.id).count(),
            1,
        )
        self.assertEqual(
            self.db.query(CrewAssignment).filter(
                CrewAssignment.crew_profile_id == profile.id,
                CrewAssignment.ended_at.is_(None),
            ).count(),
            1,
        )
        self.assertEqual(
            self.db.query(ShorePass).filter(
                ShorePass.crew_profile_id == profile.id,
                ShorePass.vessel_name == self.vessel.name,
            ).count(),
            1,
        )
        self.assertEqual(second.passport_number, normalize_passport_number(passport))
        self.db.refresh(self.vessel)
        self.assertEqual(self.vessel.crew_count, 1)
        self.assertEqual(self.vessel.total_crew, 1)

    def test_identical_retry_updates_shore_pass_settings(self):
        passport = _uniq("R").replace("-", "")
        self.add_profile(passport=passport)
        first = self.add(self.body(passport_number=passport, shore_pass_eligible=True))
        valid_upto = datetime.now(timezone.utc) + timedelta(days=1)

        second = self.add(self.body(
            passport_number=passport,
            shore_pass_eligible=False,
            shore_pass_valid_upto=valid_upto,
        ))

        self.assertEqual(second.id, first.id)
        self.assertFalse(second.shore_pass_eligible)
        self.assertEqual(second.shore_pass_valid_upto, valid_upto)
        assignment = self.db.query(CrewAssignment).filter(
            CrewAssignment.vessel_crew_id == second.id
        ).one()
        self.assertFalse(assignment.shore_pass_eligible)

    def test_shared_passport_is_rejected_for_identity_reconciliation(self):
        passport = _uniq("DUP").replace("-", "")
        self.add_profile(passport=passport, name="First Person")
        self.add_profile(passport=f" {passport.lower()} ", name="Second Person")

        with self.assertRaises(HTTPException) as caught:
            self.add(self.body(passport_number=passport))

        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("multiple crew accounts", caught.exception.detail["message"])
        self.assertEqual(caught.exception.detail["status"], "OPEN")
        self.assertIsNotNone(caught.exception.detail["identity_conflict_id"])
        self.assertEqual(
            self.db.query(CrewIdentityConflictRecord).filter(
                CrewIdentityConflictRecord.id
                == caught.exception.detail["identity_conflict_id"]
            ).count(),
            1,
        )
        with self.assertRaises(HTTPException) as repeated:
            self.add(self.body(passport_number=passport))
        self.assertEqual(
            repeated.exception.detail["identity_conflict_id"],
            caught.exception.detail["identity_conflict_id"],
        )
        self.assertEqual(
            repeated.exception.detail["version"],
            caught.exception.detail["version"] + 1,
        )
        self.assertEqual(
            self.db.query(VesselCrew).filter(VesselCrew.vessel_id == self.vessel.id).count(),
            0,
        )

    def test_passport_with_conflicting_nationality_is_not_silently_linked(self):
        passport = _uniq("NAT").replace("-", "")
        self.add_profile(passport=passport, nationality="PH")

        with self.assertRaises(HTTPException) as caught:
            self.add(self.body(passport_number=passport, nationality="Indian"))

        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("different nationality", caught.exception.detail["message"])

    def test_passport_with_conflicting_name_is_not_silently_linked(self):
        passport = _uniq("WHO").replace("-", "")
        self.add_profile(passport=passport, name="Different Person")

        with self.assertRaises(HTTPException) as caught:
            self.add(self.body(passport_number=passport, name="Ravi Kumar"))

        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("different crew name", caught.exception.detail["message"])

    def test_existing_manifest_with_different_name_is_not_overwritten(self):
        passport = _uniq("NAME").replace("-", "")
        first = self.add(self.body(passport_number=passport, name="Ravi Kumar"))

        with self.assertRaises(HTTPException) as caught:
            self.add(self.body(passport_number=passport, name="Another Person"))

        self.assertEqual(caught.exception.status_code, 409)
        self.db.refresh(first)
        self.assertEqual(first.name, "Ravi Kumar")

    def test_resolution_is_audited_and_only_authorizes_the_same_identity(self):
        from app.api.v1.routes_superadmin import (
            IdentityConflictResolutionIn,
            get_identity_conflict,
            list_identity_conflicts,
            resolve_identity_conflict,
        )
        from app.db.models.crew_identity_conflict import CrewIdentityConflictAudit

        passport = _uniq("QUEUE").replace("-", "")
        selected = self.add_profile(passport=passport, name="Ravi Kumar")
        self.add_profile(passport=passport, nationality="PH", name="Other Person")
        superadmin = User(
            email=f"{_uniq('superadmin')}@example.com",
            hashed_password="x",
            role="superadmin",
        )
        self.db.add(superadmin)
        self.db.flush()

        with self.assertRaises(HTTPException) as first_conflict:
            self.add(self.body(passport_number=passport, name="Ravi Kumar"))
        detail = first_conflict.exception.detail
        conflict_id = detail["identity_conflict_id"]

        queue = list_identity_conflicts(
            status_filter="OPEN", page=1, limit=50,
            db=self.db, current_user=superadmin,
        )
        self.assertIn(conflict_id, [item["id"] for item in queue["items"]])
        resolved = resolve_identity_conflict(
            conflict_id=conflict_id,
            body=IdentityConflictResolutionIn(
                expected_version=detail["version"],
                action="SELECT_PROFILE",
                crew_profile_id=selected.id,
                evidence_type="passport_scan",
                evidence_reference="DOC-123",
                reason="Verified against the signed passport scan",
            ),
            db=self.db,
            current_user=superadmin,
        )
        self.assertEqual(resolved["status"], "RESOLVED")
        self.assertEqual(resolved["version"], detail["version"] + 1)
        self.assertEqual(resolved["selected_profile_id"], selected.id)
        self.assertEqual(len(resolved["audits"]), 1)
        self.assertEqual(resolved["vessel"]["id"], self.vessel.id)
        self.assertEqual(resolved["candidates"][0]["id"], selected.id)
        self.assertEqual(resolved["resolution"]["action"], "SELECT_PROFILE")
        self.assertEqual(
            self.db.query(CrewIdentityConflictAudit).filter(
                CrewIdentityConflictAudit.conflict_id == conflict_id
            ).count(),
            1,
        )
        self.assertEqual(
            get_identity_conflict(
                conflict_id=conflict_id, db=self.db, current_user=superadmin
            )["audits"][0]["actor_user_id"],
            superadmin.id,
        )

        mapped = self.add(self.body(passport_number=passport, name="Ravi Kumar"))
        assignment = self.db.query(CrewAssignment).filter(
            CrewAssignment.vessel_crew_id == mapped.id
        ).one()
        self.assertEqual(assignment.crew_profile_id, selected.id)

        # The decision is fingerprinted. Reusing the passport with a different
        # identity opens a new queue item rather than silently linking the
        # profile selected for Ravi.
        with self.assertRaises(HTTPException) as stale_decision:
            self.add(self.body(passport_number=passport, name="Different Name"))
        self.assertNotEqual(
            stale_decision.exception.detail["identity_conflict_id"], conflict_id
        )
        self.assertIn("identity", stale_decision.exception.detail["message"])

    def test_identity_conflict_queue_is_superadmin_only_and_versioned(self):
        from app.api.v1.routes_superadmin import (
            IdentityConflictResolutionIn,
            list_identity_conflicts,
            resolve_identity_conflict,
        )

        passport = _uniq("STALE").replace("-", "")
        selected = self.add_profile(passport=passport, name="Ravi Kumar")
        self.add_profile(passport=passport, nationality="PH", name="Other Person")
        with self.assertRaises(HTTPException) as conflict:
            self.add(self.body(passport_number=passport))
        conflict_id = conflict.exception.detail["identity_conflict_id"]

        with self.assertRaises(HTTPException) as forbidden:
            list_identity_conflicts(
                status_filter="OPEN", page=1, limit=50,
                db=self.db, current_user=self.agent,
            )
        self.assertEqual(forbidden.exception.status_code, 403)

        superadmin = User(
            email=f"{_uniq('superadmin')}@example.com",
            hashed_password="x", role="superadmin",
        )
        self.db.add(superadmin)
        self.db.flush()
        with self.assertRaises(HTTPException) as stale:
            resolve_identity_conflict(
                conflict_id=conflict_id,
                body=IdentityConflictResolutionIn(
                    expected_version=999,
                    action="SELECT_PROFILE",
                    crew_profile_id=selected.id,
                    evidence_type="passport_scan",
                    reason="Verified against source documents",
                ),
                db=self.db,
                current_user=superadmin,
            )
        self.assertEqual(stale.exception.status_code, 409)
        self.assertEqual(
            stale.exception.detail["current_version"],
            conflict.exception.detail["version"],
        )

    def test_nationality_is_required_at_the_api_boundary(self):
        with self.assertRaises(ValidationError):
            CrewMemberIn(
                name="Ravi Kumar",
                rank="AB",
                passport_number="P12345",
                nationality=None,
            )


if __name__ == "__main__":
    unittest.main()
