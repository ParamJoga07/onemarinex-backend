from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.routes_auth import get_current_user
from app.db.models.crew_sos import CrewSos
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


class SosTimelineEvent(BaseModel):
    event: str
    label: str
    time: Optional[datetime] = None
    done: bool


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
    events: List[SosTimelineEvent]


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

    events: List[SosTimelineEvent] = [
        SosTimelineEvent(
            event="TRIGGERED",
            label="SOS triggered by crew",
            time=sos.created_at,
            done=True,
        ),
        SosTimelineEvent(
            event="ACKNOWLEDGED",
            label="Acknowledged by admin",
            time=sos.acknowledged_at,
            done=sos.acknowledged_at is not None,
        ),
    ]
    if sos.cancelled_at is not None:
        events.append(SosTimelineEvent(
            event="CANCELLED",
            label="Cancelled by crew",
            time=sos.cancelled_at,
            done=True,
        ))
    else:
        events.append(SosTimelineEvent(
            event="CLOSED",
            label="Resolved & closed",
            time=sos.closed_at,
            done=sos.closed_at is not None,
        ))

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

    sos = db.query(CrewSos).filter(CrewSos.id == sos_id).first()
    if not sos:
        raise HTTPException(status_code=404, detail="SOS request not found")

    if not _agent_may_handle(db, current_user, sos):
        # Same response as a missing record, so an agent cannot probe for other
        # agencies' SOS ids.
        raise HTTPException(status_code=404, detail="SOS request not found")

    status_value = body.status.strip().upper()
    if status_value not in {"ACTIVE", "ACKNOWLEDGED", "CLOSED", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="Invalid SOS status")

    sos.status = status_value
    if status_value == "ACKNOWLEDGED":
        sos.acknowledged_at = datetime.utcnow()
    if status_value == "CLOSED":
        sos.closed_at = datetime.utcnow()
    if status_value == "CANCELLED":
        sos.cancelled_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(sos)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    return sos
