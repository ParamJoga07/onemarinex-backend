"""Audited Superadmin handling for ambiguous crew identities.

The queue is deliberately not an identity merge tool.  A human decision only
authorises an exact later manifest retry, and resolving the queue item must not
rewrite any CrewProfile row or bypass optimistic concurrency.
"""

import hashlib
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401 - register all mapped tables
from app.api.v1.routes_superadmin import (
    IdentityConflictResolutionIn,
    get_identity_conflict,
    list_identity_conflicts,
    resolve_identity_conflict,
)
from app.db.models.crew_identity_conflict import (
    CrewIdentityConflictAudit,
    CrewIdentityConflictRecord,
)
from app.db.models.crew_profile import CrewProfile
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.session import engine


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.fixture()
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def queue_case(db):
    admin = User(
        email=f"{_uniq('admin')}@example.com",
        hashed_password="x",
        role="superadmin",
    )
    agent = User(
        email=f"{_uniq('agent')}@example.com",
        hashed_password="x",
        role="agent",
    )
    crew_users = [
        User(
            email=f"{_uniq('crew')}@example.com",
            hashed_password="x",
            role="crew",
        )
        for _ in range(3)
    ]
    db.add_all([admin, agent, *crew_users])
    db.flush()
    vessel = Vessel(
        agent_id=agent.id,
        name=_uniq("MV CONFLICT"),
        imo_number=_uniq("IMO"),
        vessel_type="Bulk Carrier",
        status="Active",
    )
    candidates = [
        CrewProfile(
                user_id=user.id,
                full_name=f"Candidate {index}",
                rank="able_seaman",
            nationality="IN",
            passport_number="AMB123",
            hpid=_uniq("HP"),
        )
        for index, user in enumerate(crew_users[:2], start=1)
    ]
    outsider = CrewProfile(
            user_id=crew_users[2].id,
            full_name="Not a candidate",
            rank="able_seaman",
        nationality="PH",
        passport_number="OTHER999",
        hpid=_uniq("HP"),
    )
    db.add_all([vessel, *candidates, outsider])
    db.flush()
    proposed = {
        "name": "Candidate One",
        "nationality": "IN",
        "passport_number": "AMB123",
    }
    conflict = CrewIdentityConflictRecord(
        operation="BULK_MANIFEST",
        vessel_id=vessel.id,
        passport_key="AMB123",
        identity_fingerprint=hashlib.sha256(b"exact-proposal").hexdigest(),
        proposed_identity=proposed,
        candidate_profile_ids=[profile.id for profile in candidates],
        conflict_message="Passport matches multiple verified profiles",
        status="OPEN",
        version=3,
    )
    db.add(conflict)
    db.flush()
    return {
        "admin": admin,
        "agent": agent,
        "vessel": vessel,
        "candidates": candidates,
        "outsider": outsider,
        "conflict": conflict,
    }


def _resolution(case, **overrides):
    values = {
        "expected_version": 3,
        "action": "SELECT_PROFILE",
        "crew_profile_id": case["candidates"][0].id,
        "evidence_type": "signed_manifest",
        "evidence_reference": "MANIFEST-PAGE-3",
        "reason": "Verified against the signed vessel manifest.",
    }
    values.update(overrides)
    return IdentityConflictResolutionIn(**values)


def test_only_superadmin_can_list_or_read_identity_conflicts(db, queue_case):
    with pytest.raises(HTTPException) as denied_list:
        list_identity_conflicts(db=db, current_user=queue_case["agent"])
    with pytest.raises(HTTPException) as denied_detail:
        get_identity_conflict(
            queue_case["conflict"].id,
            db=db,
            current_user=queue_case["agent"],
        )

    assert denied_list.value.status_code == 403
    assert denied_detail.value.status_code == 403


def test_queue_payload_round_trips_real_backend_contract(db, queue_case):
    response = list_identity_conflicts(
        status_filter="OPEN",
        page=1,
        limit=50,
        db=db,
        current_user=queue_case["admin"],
    )
    row = next(
        item for item in response["items"]
        if item["id"] == queue_case["conflict"].id
    )

    assert row["vessel_name"] == queue_case["vessel"].name
    assert row["message"] == "Passport matches multiple verified profiles"
    assert {item["id"] for item in row["candidate_profiles"]} == {
        profile.id for profile in queue_case["candidates"]
    }
    assert row["status"] == "OPEN"
    assert row["version"] == 3


def test_stale_or_non_candidate_resolution_is_rejected(db, queue_case):
    with pytest.raises(HTTPException) as stale:
        resolve_identity_conflict(
            queue_case["conflict"].id,
            _resolution(queue_case, expected_version=2),
            db=db,
            current_user=queue_case["admin"],
        )
    assert stale.value.status_code == 409

    with pytest.raises(HTTPException) as outsider:
        resolve_identity_conflict(
            queue_case["conflict"].id,
            _resolution(
                queue_case,
                crew_profile_id=queue_case["outsider"].id,
            ),
            db=db,
            current_user=queue_case["admin"],
        )
    assert outsider.value.status_code == 409
    db.refresh(queue_case["conflict"])
    assert queue_case["conflict"].status == "OPEN"
    assert db.query(CrewIdentityConflictAudit).filter(
        CrewIdentityConflictAudit.conflict_id == queue_case["conflict"].id
    ).count() == 0


def test_resolution_is_versioned_audited_and_does_not_mutate_identity(
    db, queue_case
):
    candidate = queue_case["candidates"][0]
    identity_before = (
        candidate.full_name,
        candidate.nationality,
        candidate.passport_number,
        candidate.hpid,
    )

    result = resolve_identity_conflict(
        queue_case["conflict"].id,
        _resolution(queue_case),
        db=db,
        current_user=queue_case["admin"],
    )

    assert result["status"] == "RESOLVED"
    assert result["version"] == 4
    assert result["resolution_action"] == "SELECT_PROFILE"
    assert result["selected_profile_id"] == candidate.id
    assert len(result["audits"]) == 1
    assert result["audits"][0]["expected_version"] == 3
    assert result["audits"][0]["before"]["status"] == "OPEN"
    assert result["audits"][0]["after"]["status"] == "RESOLVED"
    db.refresh(candidate)
    assert (
        candidate.full_name,
        candidate.nationality,
        candidate.passport_number,
        candidate.hpid,
    ) == identity_before

    with pytest.raises(HTTPException) as duplicate:
        resolve_identity_conflict(
            queue_case["conflict"].id,
            _resolution(queue_case, expected_version=4),
            db=db,
            current_user=queue_case["admin"],
        )
    assert duplicate.value.status_code == 409
