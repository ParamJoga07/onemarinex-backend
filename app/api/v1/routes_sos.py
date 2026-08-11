from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.routes_auth import get_current_user
from app.db.models.crew_sos import CrewSos, CrewSosNote, CrewSosTimelineEvent
from app.db.models.crew_profile import CrewProfile
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter()


class SosStatusUpdateIn(BaseModel):
    status: str


class SosStatusOut(BaseModel):
    id: int
    status: str

    class Config:
        from_attributes = True


class SosAdminOut(BaseModel):
    id: int
    status: str
    port_name: Optional[str] = None
    vessel: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    created_at: datetime
    crew_name: Optional[str] = None
    crew_email: Optional[str] = None
    sos_email: Optional[str] = None
    crew_phone: Optional[str] = None
    trip_id: Optional[str] = None

    class Config:
        from_attributes = True


def _agent_crew_profile_ids(db: Session, agent_user_id: int) -> List[int]:
    """Crew sailing on this agent's vessels.

    SOS was scoped by port, which meant every agency berthed at the same port
    could see, acknowledge and close each other's emergencies. An agent is
    responsible for their own ships' crew, so that is the boundary.
    """
    from app.db.models.vessel import Vessel
    from app.db.models.vessel_crew import VesselCrew
    from app.db.models.crew_profile import CrewProfile

    vessel_ids = [v.id for v in db.query(Vessel.id).filter(Vessel.agent_id == agent_user_id).all()]
    if not vessel_ids:
        return []
    hpids = [
        c.hp_id for c in db.query(VesselCrew.hp_id).filter(
            VesselCrew.vessel_id.in_(vessel_ids), VesselCrew.hp_id.isnot(None)
        ).all() if c.hp_id
    ]
    if not hpids:
        return []
    return [cp.id for cp in db.query(CrewProfile.id).filter(CrewProfile.hpid.in_(hpids)).all()]


def _agent_may_handle(db: Session, current_user, sos: CrewSos) -> bool:
    if current_user.role == "superadmin":
        return True
    return sos.crew_profile_id in _agent_crew_profile_ids(db, current_user.id)


@router.get("/admin", response_model=List[SosAdminOut])
def list_sos_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {"superadmin", "agent"}:
        raise HTTPException(status_code=403, detail="Only superadmins or agents can view SOS")

    if current_user.role == "agent":
        crew_ids = _agent_crew_profile_ids(db, current_user.id)
        if not crew_ids:
            return []
        sos_list = (
            db.query(CrewSos)
            .filter(CrewSos.crew_profile_id.in_(crew_ids))
            .order_by(CrewSos.created_at.desc())
            .all()
        )
    else:
        sos_list = db.query(CrewSos).order_by(CrewSos.created_at.desc()).all()

    return [
        {
            "id": sos.id,
            "status": sos.status,
            "port_name": sos.port_name,
            "vessel": sos.vessel,
            "lat": sos.lat,
            "lng": sos.lng,
            "created_at": sos.created_at,
            "crew_name": sos.crew_profile.full_name if sos.crew_profile else None,
            "crew_email": sos.crew_email or (sos.user.email if sos.user else None),
            "sos_email": sos.sos_email,
            "crew_phone": sos.user.mobile_number if sos.user else None,
            "trip_id": sos.trip_id,
        }
        for sos in sos_list
    ]


class SosTimelineEventOut(BaseModel):
    event: str
    label: str
    time: Optional[datetime] = None
    done: bool
    # Derived lifecycle rows have no id and are never editable. Rows an agent
    # added carry their id so the screen can offer edit and delete on exactly
    # those, and the audit trail stays untouchable.
    id: Optional[int] = None
    source: str = "system"
    detail: Optional[str] = None
    actor_name: Optional[str] = None
    editable: bool = False


class SosTimelineOut(BaseModel):
    id: int
    status: str
    crew_name: Optional[str] = None
    crew_email: Optional[str] = None
    sos_email: Optional[str] = None
    crew_phone: Optional[str] = None
    trip_id: Optional[str] = None
    port_name: Optional[str] = None
    vessel: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    events: List[SosTimelineEventOut]
    timeline: List[dict] = Field(default_factory=list)
    notes: List[dict] = Field(default_factory=list)
    vessel_details: Optional[dict] = None
    crew_details: Optional[dict] = None
    trip: Optional[dict] = None


class SosCustomUpdateIn(BaseModel):
    label: str
    detail: Optional[str] = None


class SosNoteIn(BaseModel):
    note: str


@router.get("/{sos_id}/timeline", response_model=SosTimelineOut)
def get_sos_timeline(
    sos_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ordered timeline of an SOS request's lifecycle for the admin view."""
    if current_user.role not in {"superadmin", "agent"}:
        raise HTTPException(status_code=403, detail="Only superadmins or agents can view SOS")

    sos = db.query(CrewSos).filter(CrewSos.id == sos_id).first()
    if not sos:
        raise HTTPException(status_code=404, detail="SOS request not found")

    if not _agent_may_handle(db, current_user, sos):
        # Same response as a missing record, so an agent cannot probe for other
        # agencies' SOS ids.
        raise HTTPException(status_code=404, detail="SOS request not found")

    events: List[SosTimelineEventOut] = [
        SosTimelineEventOut(
            event="TRIGGERED",
            label="SOS triggered by crew",
            time=sos.created_at,
            done=True,
        ),
        SosTimelineEventOut(
            event="ACKNOWLEDGED",
            label="Acknowledged by admin",
            time=sos.acknowledged_at,
            done=sos.acknowledged_at is not None,
        ),
    ]
    if sos.cancelled_at is not None:
        events.append(SosTimelineEventOut(
            event="CANCELLED",
            label="Cancelled by crew",
            time=sos.cancelled_at,
            done=True,
        ))
    else:
        events.append(SosTimelineEventOut(
            event="CLOSED",
            label="Resolved & closed",
            time=sos.closed_at,
            done=sos.closed_at is not None,
        ))

    from app.db.models.vessel import Vessel
    from app.db.models.vessel_crew import VesselCrew
    from app.services.operations_context import booking_context, find_booking, vessel_context

    vessel = None
    if sos.crew_profile and sos.crew_profile.hpid:
        vessel = (
            db.query(Vessel)
            .join(VesselCrew, VesselCrew.vessel_id == Vessel.id)
            .filter(VesselCrew.hp_id == sos.crew_profile.hpid)
            .first()
        )
    if vessel is None and sos.vessel:
        vessel = db.query(Vessel).filter(Vessel.name == sos.vessel).first()
    booking = find_booking(db, sos.trip_id, booking_id=sos.cab_booking_id)

    persisted_timeline = (
        db.query(CrewSosTimelineEvent)
        .filter(CrewSosTimelineEvent.sos_id == sos.id)
        .order_by(CrewSosTimelineEvent.event_time.asc(), CrewSosTimelineEvent.id.asc())
        .all()
    )
    timeline = [
        {
            "id": item.id,
            "source": item.source,
            "event_type": item.event_type,
            "label": item.label,
            "detail": item.detail,
            "actor_name": item.actor_name,
            "event_time": item.event_time,
        }
        for item in persisted_timeline
    ]
    if not timeline:
        # Legacy SOS rows predate the event table. Preserve their real stamps
        # instead of manufacturing new times during migration.
        timeline = [
            {
                "id": None, "source": "system", "event_type": item.event,
                "label": item.label, "detail": None, "actor_name": None,
                "event_time": item.time,
            }
            for item in events if item.time is not None
        ]
    notes = (
        db.query(CrewSosNote)
        .filter(CrewSosNote.sos_id == sos.id)
        .order_by(CrewSosNote.created_at.asc(), CrewSosNote.id.asc())
        .all()
    )

    return SosTimelineOut(
        id=sos.id,
        status=sos.status,
        crew_name=sos.crew_profile.full_name if sos.crew_profile else None,
        crew_email=sos.crew_email or (sos.user.email if sos.user else None),
        sos_email=sos.sos_email,
        crew_phone=sos.user.mobile_number if sos.user else None,
        trip_id=sos.trip_id,
        port_name=sos.port_name,
        vessel=sos.vessel,
        lat=sos.lat,
        lng=sos.lng,
        events=events,
        timeline=timeline,
        notes=[{
            "id": note.id, "author_name": note.author_name,
            "note": note.note, "created_at": note.created_at,
        } for note in notes],
        vessel_details=vessel_context(vessel, port_name=sos.port_name),
        crew_details={
            "name": sos.crew_profile.full_name if sos.crew_profile else None,
            "rank": sos.crew_profile.rank if sos.crew_profile else None,
            "nationality": sos.crew_profile.nationality if sos.crew_profile else None,
            "phone": sos.user.mobile_number if sos.user else None,
            "email": sos.crew_email or (sos.user.email if sos.user else None),
        },
        # As of when the SOS was raised: where the crew actually were at that
        # moment, not wherever the cab ended up afterwards.
        trip=booking_context(db, booking, as_of=sos.created_at),
    )


@router.patch("/{sos_id}/status", response_model=SosStatusOut)
def update_sos_status(
    sos_id: int,
    body: SosStatusUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {"superadmin", "agent"}:
        raise HTTPException(status_code=403, detail="Only superadmins or agents can update SOS")

    sos = db.query(CrewSos).filter(CrewSos.id == sos_id).with_for_update().first()
    if not sos:
        raise HTTPException(status_code=404, detail="SOS request not found")

    if not _agent_may_handle(db, current_user, sos):
        # Same response as a missing record, so an agent cannot probe for other
        # agencies' SOS ids.
        raise HTTPException(status_code=404, detail="SOS request not found")

    status_value = body.status.strip().upper()
    if status_value not in {"ACTIVE", "ACKNOWLEDGED", "CLOSED", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="Invalid SOS status")

    current_status = (sos.status or "ACTIVE").upper()
    if status_value == current_status:
        return sos
    allowed = {
        "ACTIVE": {"ACKNOWLEDGED", "CLOSED", "CANCELLED"},
        "ACKNOWLEDGED": {"CLOSED", "CANCELLED"},
        "CLOSED": set(),
        "CANCELLED": set(),
    }
    if status_value not in allowed.get(current_status, set()):
        raise HTTPException(status_code=409, detail="This SOS alert is already in a terminal state")

    sos.status = status_value
    if status_value == "ACKNOWLEDGED":
        sos.acknowledged_at = datetime.utcnow()
    if status_value == "CLOSED":
        sos.closed_at = datetime.utcnow()
    if status_value == "CANCELLED":
        sos.cancelled_at = datetime.utcnow()

    labels = {
        "ACKNOWLEDGED": "Agent responding",
        "CLOSED": "SOS resolved and closed",
        "CANCELLED": "SOS cancelled",
    }
    db.add(CrewSosTimelineEvent(
        sos_id=sos.id,
        source="system",
        event_type=status_value,
        label=labels[status_value],
        actor_name=getattr(current_user, "name", None),
    ))

    try:
        db.commit()
        db.refresh(sos)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return sos


@router.post("/{sos_id}/updates")
def add_sos_update(
    sos_id: int,
    body: SosCustomUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {"superadmin", "agent"}:
        raise HTTPException(status_code=403, detail="Only superadmins or agents can add updates")
    sos = db.query(CrewSos).filter(CrewSos.id == sos_id).first()
    if not sos or not _agent_may_handle(db, current_user, sos):
        raise HTTPException(status_code=404, detail="SOS request not found")
    if (sos.status or "ACTIVE").upper() in {"CLOSED", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Timeline updates are locked for a terminal SOS alert")
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Update label is required")
    event = CrewSosTimelineEvent(
        sos_id=sos.id,
        source="agent",
        event_type="UPDATE",
        label=label,
        detail=(body.detail or "").strip() or None,
        actor_name=getattr(current_user, "name", None),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {
        "id": event.id, "source": event.source, "event_type": event.event_type,
        "label": event.label, "detail": event.detail,
        "actor_name": event.actor_name, "event_time": event.event_time,
    }


@router.post("/{sos_id}/notes")
def add_sos_note(
    sos_id: int,
    body: SosNoteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {"superadmin", "agent"}:
        raise HTTPException(status_code=403, detail="Only superadmins or agents can add notes")
    sos = db.query(CrewSos).filter(CrewSos.id == sos_id).first()
    if not sos or not _agent_may_handle(db, current_user, sos):
        raise HTTPException(status_code=404, detail="SOS request not found")
    text_value = body.note.strip()
    if not text_value:
        raise HTTPException(status_code=400, detail="Note is required")
    note = CrewSosNote(
        sos_id=sos.id, note=text_value,
        author_name=getattr(current_user, "name", None),
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return {
        "id": note.id, "author_name": note.author_name,
        "note": note.note, "created_at": note.created_at,
    }


# --- Manual timeline entries ("custom timings") ----------------------------

class SosTimelineEntryIn(BaseModel):
    label: str
    detail: Optional[str] = None
    event_time: Optional[datetime] = None
    event_type: Optional[str] = None


SOS_MANUAL_EVENT_TYPES = {"update", "investigation", "resolved", "note"}


def _sos_manual_event_or_404(db: Session, current_user, event_id: int):
    """A manual timeline row on an SOS this agent may handle.

    The automatic triggered/acknowledged/closed entries are the alert's own
    audit trail and stay immutable; a system row reports as not found so it is
    indistinguishable from one belonging to another agency.
    """
    from app.db.models.crew_sos import CrewSosTimelineEvent

    event = db.query(CrewSosTimelineEvent).filter(
        CrewSosTimelineEvent.id == event_id
    ).first()
    if not event:
        raise HTTPException(status_code=404, detail="Timeline entry not found")

    sos = db.query(CrewSos).filter(CrewSos.id == event.sos_id).first()
    if not sos or not _agent_may_handle(db, current_user, sos):
        raise HTTPException(status_code=404, detail="Timeline entry not found")

    if (event.source or "system") != "agent":
        raise HTTPException(status_code=404, detail="Timeline entry not found")

    # Same rule the creator applies: once an alert is closed or cancelled its
    # timeline is the record of what happened and stops accepting changes.
    if (sos.status or "ACTIVE").upper() in {"CLOSED", "CANCELLED"}:
        raise HTTPException(status_code=409,
                            detail="Timeline updates are locked for a terminal SOS alert")
    return event


def _sos_timeline_out(event) -> dict:
    return {
        "id": event.id,
        "source": event.source,
        "event_type": event.event_type,
        "label": event.label,
        "detail": event.detail,
        "actor_name": event.actor_name,
        "event_time": event.event_time,
        "editable": (event.source or "system") == "agent",
    }


@router.patch("/timeline/{event_id}")
def edit_sos_timeline_entry(
    event_id: int,
    body: SosTimelineEntryIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {"superadmin", "agent"}:
        raise HTTPException(status_code=403, detail="Only superadmins or agents can edit updates")
    event = _sos_manual_event_or_404(db, current_user, event_id)

    label = (body.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="An update needs a label")
    event.label = label
    event.detail = (body.detail or "").strip() or None
    if body.event_time is not None:
        event.event_time = body.event_time
    if body.event_type:
        event_type = body.event_type.strip().lower()
        if event_type not in SOS_MANUAL_EVENT_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown update type: {event_type}")
        event.event_type = event_type
    db.commit()
    db.refresh(event)
    return _sos_timeline_out(event)


@router.delete("/timeline/{event_id}")
def delete_sos_timeline_entry(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {"superadmin", "agent"}:
        raise HTTPException(status_code=403, detail="Only superadmins or agents can delete updates")
    event = _sos_manual_event_or_404(db, current_user, event_id)
    db.delete(event)
    db.commit()
    return {"deleted": True, "id": event_id}
