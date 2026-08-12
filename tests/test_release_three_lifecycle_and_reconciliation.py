from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401
from app.api.v1.routes_superadmin import (
    HistoricalContextResolutionIn,
    reconcile_historical_context,
)
from app.api.v1.routes_vessels import get_agent_vessel_call_history
from app.db.models.agent_profile import AgentProfile
from app.db.models.event_context_reconciliation import EventContextReconciliation
from app.db.models.incident import Incident, IncidentStatus, IncidentType
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.session import engine
from app.services.historical_context import active_vessel_call, finish_vessel_call
from app.services.vessel_lifecycle import (
    effective_vessel_status,
    synchronize_vessel_lifecycle,
)


ROOT = Path(__file__).resolve().parents[1]


def _uniq(prefix):
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


def _agent_and_vessel(db, *, etd=None):
    user = User(email=f"{_uniq('agent')}@example.com", hashed_password="x", role="agent")
    db.add(user)
    db.flush()
    agency = AgentProfile(user_id=user.id, agency_name=_uniq("Agency"), location="Port")
    vessel = Vessel(
        agent_id=user.id,
        name=_uniq("MV"),
        imo_number=_uniq("IMO"),
        vessel_type="Bulk Carrier",
        status="Active",
        etd=etd,
    )
    db.add_all([agency, vessel])
    db.flush()
    call = active_vessel_call(db, vessel)
    return user, agency, vessel, call


def test_release_three_is_the_only_head():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["o6p7q8r9s0t1"]
    assert script.get_revision("o6p7q8r9s0t1").down_revision == "n5o6p7q8r9s0"


def test_status_uses_server_time_and_24_hour_departing_window():
    now = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    vessel = Vessel(status="Active", etd=now + timedelta(hours=25))
    assert effective_vessel_status(vessel, now=now) == "Active"
    vessel.etd = now + timedelta(hours=24)
    assert effective_vessel_status(vessel, now=now) == "Departing"
    vessel.etd = now
    assert effective_vessel_status(vessel, now=now) == "Departed"
    vessel.status = "Archived"
    vessel.etd = now + timedelta(days=100)
    assert effective_vessel_status(vessel, now=now) == "Archived"


def test_departure_finishes_call_at_etd_and_history_remains_agent_visible(db):
    now = datetime.now(timezone.utc)
    agent, agency, vessel, call = _agent_and_vessel(db, etd=now - timedelta(minutes=5))
    changed = synchronize_vessel_lifecycle(db, [vessel], now=now)
    db.flush()
    assert changed
    assert vessel.status == "Departed"
    assert call.status == "DEPARTED"
    assert call.ended_at == vessel.etd

    history = get_agent_vessel_call_history(current_user=agent, db=db)
    row = next(item for item in history if item["vessel_call_id"] == call.id)
    assert row["vessel_name"] == vessel.name
    assert row["status"] == "DEPARTED"
    assert agency.id == call.agency_id


def test_agent_history_does_not_expose_another_agencys_call(db):
    agent, _agency, _vessel, own_call = _agent_and_vessel(db)
    other_agent, _other_agency, _other_vessel, other_call = _agent_and_vessel(db)
    finish_vessel_call(db, _vessel, status="DEPARTED")
    finish_vessel_call(db, _other_vessel, status="DEPARTED")
    db.flush()

    history = get_agent_vessel_call_history(current_user=agent, db=db)
    visible_ids = {item["vessel_call_id"] for item in history}
    assert own_call.id in visible_ids
    assert other_call.id not in visible_ids
    assert other_agent.id != agent.id


def test_manual_reconciliation_updates_context_and_writes_audit(db):
    _agent, agency, vessel, call = _agent_and_vessel(db)
    incident = Incident(
        incident_id=_uniq("INC"),
        type=IncidentType.CREW,
        title="Legacy event",
        description="Needs reviewed historical ownership.",
        status=IncidentStatus.RESOLVED,
        context_resolution="unresolved",
    )
    admin = User(email=f"{_uniq('admin')}@example.com", hashed_password="x", role="superadmin")
    db.add_all([incident, admin])
    db.flush()

    result = reconcile_historical_context(
        record_kind="incident",
        record_id=incident.id,
        body=HistoricalContextResolutionIn(
            vessel_call_id=call.id,
            evidence_type="agency_confirmation",
            evidence_reference="EMAIL-2026-08-12",
            notes="Agency confirmed the vessel and port-call record.",
        ),
        db=db,
        current_user=admin,
    )
    assert result["context"]["vessel_id"] == vessel.id
    assert result["context"]["agency_id"] == agency.id
    audit = db.query(EventContextReconciliation).filter(
        EventContextReconciliation.record_kind == "incident",
        EventContextReconciliation.record_id == incident.id,
    ).one()
    assert audit.previous_context["vessel_call_id"] is None
    assert audit.resolved_context["vessel_call_id"] == call.id
    assert audit.reconciled_by_user_id == admin.id


def test_agent_cannot_reconcile_historical_context(db):
    agent, _agency, _vessel, call = _agent_and_vessel(db)
    incident = Incident(
        incident_id=_uniq("INC"),
        type=IncidentType.CREW,
        title="Legacy event",
        description="Must remain superadmin-only.",
        status=IncidentStatus.ACTIVE,
        context_resolution="unresolved",
    )
    db.add(incident)
    db.flush()
    with pytest.raises(HTTPException) as denied:
        reconcile_historical_context(
            record_kind="incident",
            record_id=incident.id,
            body=HistoricalContextResolutionIn(
                vessel_call_id=call.id,
                evidence_type="manual_document",
                notes="This should never be accepted from an agent.",
            ),
            db=db,
            current_user=agent,
        )
    assert denied.value.status_code == 403


def test_reconciliation_migration_preserves_audit_on_rollback():
    source = (ROOT / "alembic/versions/o6p7q8r9s0t1_historical_context_reconciliation.py").read_text()
    assert '"event_context_reconciliations"' in source
    assert "ondelete=\"SET NULL\"" in source
    assert "pass" in source.split("def downgrade():", 1)[1]
