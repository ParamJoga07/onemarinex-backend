"""Create and resolve immutable operational vessel context.

Current profile fields answer where a person or ship is now. These helpers
stamp the vessel call, agency, crew assignment, and port onto records when an
operation happens so later reassignment cannot rewrite the event's history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models.agent_profile import AgentProfile
from app.db.models.crew_assignment import CrewAssignment
from app.db.models.crew_profile import CrewProfile
from app.db.models.port import Port
from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall
from app.db.models.vessel_crew import VesselCrew


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def agent_profile_for_vessel(db: Session, vessel: Vessel) -> Optional[AgentProfile]:
    if not vessel.agent_id:
        return None
    return (
        db.query(AgentProfile)
        .filter(AgentProfile.user_id == vessel.agent_id)
        .first()
    )


def port_for_reference(db: Session, reference: Optional[str]) -> Optional[Port]:
    value = (reference or "").strip()
    if not value:
        return None
    return db.query(Port).filter(or_(Port.code == value, Port.name == value)).first()


def active_vessel_call(
    db: Session,
    vessel: Optional[Vessel],
    *,
    create: bool = True,
) -> Optional[VesselCall]:
    if vessel is None:
        return None
    call = (
        db.query(VesselCall)
        .filter(VesselCall.vessel_id == vessel.id, VesselCall.ended_at.is_(None))
        .order_by(VesselCall.id.desc())
        .first()
    )
    if call is not None or not create:
        return call

    # A vessel call is an operational boundary, not a convenience row. Never
    # manufacture a new one while a vessel is outside current operations. The
    # lifecycle transition which reassigns/reopens a vessel must first make it
    # active and assign an agent explicitly.
    stored_status = str(vessel.status or "").strip().lower()
    if vessel.agent_id is None or stored_status in {"archived", "departed"}:
        return None

    agent = agent_profile_for_vessel(db, vessel)
    port = port_for_reference(db, agent.assigned_port if agent else None)
    call = VesselCall(
        vessel_id=vessel.id,
        agency_id=agent.id if agent else None,
        port_id=port.id if port else None,
        vessel_name=vessel.name,
        imo_number=vessel.imo_number,
        flag=vessel.flag,
        agency_name=(agent.agency_name if agent else None) or vessel.agency_name,
        port_name=(port.code if port else None) or (agent.assigned_port if agent else None),
        eta=vessel.eta,
        etd=vessel.etd,
        started_at=vessel.eta or vessel.created_at or _utcnow(),
        status="ACTIVE",
    )
    db.add(call)
    db.flush()
    # Reassigning an existing vessel starts a new call while keeping the
    # manifest rows. Materialise fresh call-specific assignments so subsequent
    # events do not fall back to person identity alone.
    manifests = db.query(VesselCrew).filter(VesselCrew.vessel_id == vessel.id).all()
    for manifest in manifests:
        assignment_for_manifest(db, vessel, manifest)
    return call


def finish_vessel_call(
    db: Session,
    vessel: Vessel,
    *,
    status: str = "ARCHIVED",
    ended_at: Optional[datetime] = None,
) -> None:
    call = active_vessel_call(db, vessel, create=False)
    if call is None:
        return
    ended_at = ended_at or _utcnow()
    call.ended_at = ended_at
    call.status = status
    db.query(CrewAssignment).filter(
        CrewAssignment.vessel_call_id == call.id,
        CrewAssignment.ended_at.is_(None),
    ).update({CrewAssignment.ended_at: ended_at}, synchronize_session="fetch")


def refresh_active_vessel_call(db: Session, vessel: Vessel) -> Optional[VesselCall]:
    """Refresh mutable voyage details while a call is still operational."""
    # Editing voyage metadata must never create a fresh call. Call creation is
    # reserved for vessel onboarding and an explicit reassignment transition.
    call = active_vessel_call(db, vessel, create=False)
    if call is None:
        return None
    agent = agent_profile_for_vessel(db, vessel)
    port = port_for_reference(db, agent.assigned_port if agent else call.port_name)
    call.vessel_name = vessel.name
    call.imo_number = vessel.imo_number
    call.flag = vessel.flag
    call.agency_id = agent.id if agent else call.agency_id
    call.agency_name = (agent.agency_name if agent else None) or vessel.agency_name
    call.port_id = port.id if port else call.port_id
    call.port_name = (port.code if port else None) or (
        agent.assigned_port if agent else call.port_name
    )
    call.eta = vessel.eta
    call.etd = vessel.etd
    return call


def crew_profile_for_manifest(
    db: Session, manifest: VesselCrew
) -> Optional[CrewProfile]:
    clauses = []
    if (manifest.hp_id or "").strip():
        clauses.append(
            func.upper(func.trim(CrewProfile.hpid))
            == manifest.hp_id.strip().upper()
        )
    if (manifest.passport_number or "").strip():
        clauses.append(
            func.upper(func.trim(CrewProfile.passport_number))
            == manifest.passport_number.strip().upper()
        )
    if not clauses:
        return None
    matches = db.query(CrewProfile).filter(or_(*clauses)).limit(2).all()
    return matches[0] if len(matches) == 1 else None


def assignment_for_manifest(
    db: Session,
    vessel: Vessel,
    manifest: VesselCrew,
    *,
    profile: Optional[CrewProfile] = None,
    create: bool = True,
) -> Optional[CrewAssignment]:
    call = active_vessel_call(db, vessel, create=create)
    if call is None:
        return None
    assignment = (
        db.query(CrewAssignment)
        .filter(
            CrewAssignment.vessel_call_id == call.id,
            CrewAssignment.vessel_crew_id == manifest.id,
            CrewAssignment.ended_at.is_(None),
        )
        .first()
    )
    if assignment is not None or not create:
        return assignment
    profile = profile or crew_profile_for_manifest(db, manifest)
    assignment = CrewAssignment(
        vessel_call_id=call.id,
        crew_profile_id=profile.id if profile else None,
        vessel_crew_id=manifest.id,
        crew_name=manifest.name,
        rank=manifest.rank,
        nationality=manifest.nationality,
        hpid=manifest.hp_id,
        passport_number=manifest.passport_number,
        shore_pass_eligible=bool(manifest.shore_pass_eligible),
        started_at=manifest.created_at or call.started_at or _utcnow(),
    )
    db.add(assignment)
    db.flush()
    return assignment


def active_assignment_for_profile(
    db: Session,
    profile: Optional[CrewProfile],
    *,
    vessel_call_id: Optional[int] = None,
) -> Optional[CrewAssignment]:
    if profile is None:
        return None
    query = db.query(CrewAssignment).filter(
        CrewAssignment.crew_profile_id == profile.id,
        CrewAssignment.ended_at.is_(None),
    )
    if vessel_call_id is not None:
        query = query.filter(CrewAssignment.vessel_call_id == vessel_call_id)
    matches = query.order_by(CrewAssignment.started_at.desc(), CrewAssignment.id.desc()).limit(2).all()
    # Without a selected trip/call, two concurrent assignments are ambiguous.
    return matches[0] if len(matches) == 1 else None


def eligible_assignments_for_profile(
    db: Session,
    profile: Optional[CrewProfile],
) -> list[CrewAssignment]:
    """All exact assignments this crew member can use for a new operation."""
    if profile is None:
        return []
    return (
        db.query(CrewAssignment)
        .join(VesselCall, VesselCall.id == CrewAssignment.vessel_call_id)
        .join(Vessel, Vessel.id == VesselCall.vessel_id)
        .filter(
            CrewAssignment.crew_profile_id == profile.id,
            CrewAssignment.ended_at.is_(None),
            VesselCall.ended_at.is_(None),
            Vessel.agent_id.isnot(None),
            func.lower(func.coalesce(Vessel.status, "")).notin_(["archived", "departed"]),
        )
        .order_by(CrewAssignment.started_at.desc(), CrewAssignment.id.desc())
        .all()
    )


def ensure_assignments_for_profile(db: Session, profile: Optional[CrewProfile]) -> None:
    """Materialise missing assignments without choosing between vessels.

    Release 1 introduced assignment rows, but older/local datasets may still
    contain only manifests. This compatibility bridge creates every exact
    current assignment and never returns an arbitrary first match.
    """
    if profile is None:
        return
    clauses = []
    if (profile.hpid or "").strip():
        clauses.append(
            func.upper(func.trim(VesselCrew.hp_id)) == profile.hpid.strip().upper()
        )
    if (profile.passport_number or "").strip():
        clauses.append(
            func.upper(func.trim(VesselCrew.passport_number))
            == profile.passport_number.strip().upper()
        )
    if not clauses:
        return
    manifests = db.query(VesselCrew).filter(or_(*clauses)).all()
    for manifest in manifests:
        vessel = db.query(Vessel).filter(Vessel.id == manifest.vessel_id).first()
        if vessel is None:
            continue
        call = active_vessel_call(db, vessel, create=False)
        if call is None and vessel.agent_id is not None and str(
            vessel.status or ""
        ).lower() not in {"archived", "departed"}:
            call = active_vessel_call(db, vessel)
        if call is not None:
            assignment_for_manifest(
                db, vessel, manifest, profile=profile, create=True
            )


def selected_assignment_for_profile(
    db: Session,
    profile: Optional[CrewProfile],
    crew_assignment_id: Optional[int],
    *,
    required_when_ambiguous: bool = True,
) -> Optional[CrewAssignment]:
    """Validate a client selection or resolve the only eligible assignment.

    This deliberately refuses passport/HPID/current-profile inference. Those
    fields identify a person, not the vessel call for a new operation.
    """
    # Materialise every exact manifest-backed assignment before deciding
    # whether implicit selection is safe. Only doing this for an empty result
    # could hide a second legacy manifest and auto-select the one assignment
    # that happened to have been materialised already.
    ensure_assignments_for_profile(db, profile)
    matches = eligible_assignments_for_profile(db, profile)
    if crew_assignment_id is not None:
        selected = next(
            (row for row in matches if row.id == crew_assignment_id), None
        )
        if selected is None:
            raise ValueError(
                "The selected vessel assignment is not active for this crew member"
            )
        return selected
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1 and required_when_ambiguous:
        raise ValueError(
            "Multiple active vessel assignments found; select a vessel before continuing"
        )
    return None


def unique_current_manifest_for_profile(
    db: Session, profile: Optional[CrewProfile]
) -> Optional[VesselCrew]:
    """Resolve the one current manifest row matching this person, or nothing.

    This is used only while creating a new unlinked event. It never repairs a
    historical row, and refuses to choose when the person is on two manifests.
    """
    if profile is None:
        return None
    clauses = []
    if (profile.hpid or "").strip():
        clauses.append(
            func.upper(func.trim(VesselCrew.hp_id)) == profile.hpid.strip().upper()
        )
    if (profile.passport_number or "").strip():
        clauses.append(
            func.upper(func.trim(VesselCrew.passport_number))
            == profile.passport_number.strip().upper()
        )
    if not clauses:
        return None
    matches = db.query(VesselCrew).filter(or_(*clauses)).limit(2).all()
    return matches[0] if len(matches) == 1 else None


def end_manifest_assignment(db: Session, manifest: VesselCrew) -> None:
    assignments = db.query(CrewAssignment).filter(
        CrewAssignment.vessel_crew_id == manifest.id,
        CrewAssignment.ended_at.is_(None),
    ).all()
    now = _utcnow()
    for assignment in assignments:
        assignment.ended_at = now


def event_context(
    db: Session,
    *,
    booking=None,
    profile: Optional[CrewProfile] = None,
    vessel: Optional[Vessel] = None,
) -> dict:
    call = None
    resolution = "unresolved"
    if booking is not None and getattr(booking, "vessel_call_id", None):
        call = db.query(VesselCall).filter(VesselCall.id == booking.vessel_call_id).first()
        resolution = "booking"
    # A booking written without immutable call context is legacy/unresolved.
    # Never create a present-day call while trying to describe its history.
    if call is None and vessel is not None:
        call = active_vessel_call(db, vessel, create=False)
        resolution = "vessel_id" if call is not None else "unresolved"
    assignment = None
    if booking is not None and getattr(booking, "crew_assignment_id", None):
        assignment = db.query(CrewAssignment).filter(
            CrewAssignment.id == booking.crew_assignment_id
        ).first()
    if assignment is None and call is not None and booking is None:
        assignment = active_assignment_for_profile(
            db, profile, vessel_call_id=call.id if call else None
        )
    if call is None and assignment is not None:
        call = assignment.vessel_call
        resolution = "assignment"
    return {
        "vessel_call": call,
        "vessel_id": call.vessel_id if call else None,
        "agency_id": call.agency_id if call else None,
        "port_id": call.port_id if call else None,
        "crew_assignment_id": assignment.id if assignment else None,
        "context_resolution": resolution,
    }


def vessel_call_context(call: Optional[VesselCall], *, fallback_port: Optional[str] = None):
    if call is None:
        return None
    return {
        "id": call.vessel_id,
        "vessel_call_id": call.id,
        "name": call.vessel_name,
        "imo_number": call.imo_number,
        "port_name": call.port_name or fallback_port,
        "flag": call.flag,
        "eta": call.eta,
        "etd": call.etd,
        "berth": call.vessel.berth_assignment if call.vessel else None,
    }
