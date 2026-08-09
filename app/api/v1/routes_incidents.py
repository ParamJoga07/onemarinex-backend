from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import uuid
from app.db.session import get_db
from app.db.models.incident import Incident, IncidentNote, IncidentStatus, IncidentType
from app.api.v1.routes_auth import get_current_user
from pydantic import BaseModel

router = APIRouter()

def get_agent_incident_filters(agent_user_id: int, db: Session):
    from app.db.models.vessel import Vessel
    from app.db.models.vessel_crew import VesselCrew
    from app.db.models.crew_profile import CrewProfile
    from app.db.models.cab_booking import CabBooking

    vessel_ids = [r[0] for r in db.query(Vessel.id).filter(Vessel.agent_id == agent_user_id).all()]
    if not vessel_ids:
        return None, None
    
    crew_hpids = [r[0] for r in db.query(VesselCrew.hp_id).filter(VesselCrew.vessel_id.in_(vessel_ids)).all() if r[0]]
    if not crew_hpids:
        return [], []
    
    crew_ids = [r[0] for r in db.query(CrewProfile.id).filter(CrewProfile.hpid.in_(crew_hpids)).all()]
    trip_ids = []
    if crew_ids:
        trip_ids = [r[0] for r in db.query(CabBooking.booking_id).filter(CabBooking.crew_id.in_(crew_ids)).all() if r[0]]
    
    return crew_hpids, trip_ids

class IncidentNoteBase(BaseModel):
    note: str
    author_name: Optional[str] = None

class IncidentNoteResponse(IncidentNoteBase):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True

class IncidentBase(BaseModel):
    type: IncidentType
    title: str
    description: str
    # The crew form has always sent `category`; until now the schema had no such
    # field so Pydantic silently dropped it and nothing was ever recorded.
    category: Optional[str] = None
    sub_category: Optional[str] = None
    severity: Optional[str] = None
    reporter_name: Optional[str] = None
    reporter_role: Optional[str] = None
    reporter_id: Optional[str] = None
    trip_id: Optional[str] = None
    port_name: Optional[str] = None

class IncidentCreate(IncidentBase):
    aggregator_id: Optional[int] = None

class IncidentResponse(IncidentBase):
    id: int
    incident_id: str
    status: IncidentStatus
    vessel_id: Optional[int] = None
    vessel_name: Optional[str] = None
    category_label: Optional[str] = None
    sub_category_label: Optional[str] = None
    resolved_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    aggregator_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    notes: List[IncidentNoteResponse] = []

    class Config:
        from_attributes = True

# --- Crew Safety Center helpers -------------------------------------------

def _agent_vessel_ids(db: Session, agent_user_id: int):
    """Vessels this agent operates."""
    from app.db.models.vessel import Vessel

    return [v.id for v in db.query(Vessel.id).filter(Vessel.agent_id == agent_user_id).all()]


def _agent_incident_filter(db: Session, agent_user_id: int):
    """Which incidents belong to this agent.

    Primarily the vessel: `incidents.vessel_id` is stamped at creation and does
    not move. Matching on the reporter's HPID alone is fragile, because an HPID
    is regenerated when a crew member is re-linked to a vessel or re-uploaded on
    a manifest — and every incident raised under the old HPID then silently
    disappeared from this list while the crew member was still aboard.

    The HPID clause is kept only for older rows written before `vessel_id`
    existed, which would otherwise vanish.
    """
    from sqlalchemy import and_, or_

    vessel_ids = _agent_vessel_ids(db, agent_user_id)
    hpids, _ = _agent_hpids_and_vessels(db, agent_user_id)
    if not vessel_ids and not hpids:
        return None

    clauses = []
    if vessel_ids:
        clauses.append(Incident.vessel_id.in_(vessel_ids))
    if hpids:
        clauses.append(and_(Incident.vessel_id.is_(None),
                            Incident.reporter_id.in_(hpids)))
    return or_(*clauses)


def _agent_hpids_and_vessels(db: Session, agent_user_id: int):
    """The HPIDs sailing on this agent's vessels, and a hpid -> vessel_id map."""
    from app.db.models.vessel import Vessel
    from app.db.models.vessel_crew import VesselCrew

    vessel_ids = [v.id for v in db.query(Vessel).filter(Vessel.agent_id == agent_user_id).all()]
    if not vessel_ids:
        return [], {}
    rows = db.query(VesselCrew.hp_id, VesselCrew.vessel_id).filter(
        VesselCrew.vessel_id.in_(vessel_ids), VesselCrew.hp_id.isnot(None)
    ).all()
    hpid_to_vessel = {r[0]: r[1] for r in rows if r[0]}
    return list(hpid_to_vessel.keys()), hpid_to_vessel


def _resolve_vessel_for_reporter(db: Session, reporter_hpid: Optional[str]) -> Optional[int]:
    """Which ship a reporter sails on, so an incident can be linked to it.

    Set once at creation. Relying on the HPID lookup at read time meant an
    incident became unfindable the moment a crew member left the manifest.
    """
    if not reporter_hpid:
        return None
    from app.db.models.vessel_crew import VesselCrew

    row = db.query(VesselCrew.vessel_id).filter(VesselCrew.hp_id == reporter_hpid).first()
    return row[0] if row else None


def _record_timeline(db: Session, incident: Incident, event_type: str, label: str,
                     detail: Optional[str] = None, source: str = "system",
                     actor_name: Optional[str] = None) -> None:
    """Append one entry to an incident's timeline."""
    from app.db.models.incident import IncidentTimelineEvent

    db.add(IncidentTimelineEvent(
        incident_id=incident.id,
        source=source,
        event_type=event_type,
        label=label,
        detail=detail,
        actor_name=actor_name,
    ))


def _serialize_incident(db: Session, incident: Incident) -> dict:
    from app.services import incident_taxonomy as tax
    from app.db.models.vessel import Vessel

    vessel_name = None
    if incident.vessel_id:
        v = db.query(Vessel.name).filter(Vessel.id == incident.vessel_id).first()
        vessel_name = v[0] if v else None

    return {
        "id": incident.id,
        "incident_id": incident.incident_id,
        "type": incident.type,
        "title": incident.title,
        "description": incident.description,
        "status": incident.status,
        "category": incident.category,
        "sub_category": incident.sub_category,
        "severity": incident.severity,
        "category_label": tax.category_label(incident.category),
        "sub_category_label": tax.sub_category_label(incident.category, incident.sub_category),
        "reporter_name": incident.reporter_name,
        "reporter_role": incident.reporter_role,
        "reporter_id": incident.reporter_id,
        "trip_id": incident.trip_id,
        "port_name": incident.port_name,
        "vessel_id": incident.vessel_id,
        "vessel_name": vessel_name,
        "resolved_at": incident.resolved_at,
        "cancelled_at": incident.cancelled_at,
        "created_at": incident.created_at,
        # Required by IncidentResponse, which the status endpoint returns
        # through. Omitting it made every status change commit and then fail
        # response validation with a 500, so the client saw an error for a
        # change that had actually been saved.
        "updated_at": incident.updated_at,
    }


@router.get("/categories")
def list_incident_categories():
    """The category tree, served from one place so every form agrees.

    The rank list taught us what happens when a taxonomy is copied into each
    screen instead: three copies, two value formats, and unusable reports.
    """
    from app.services import incident_taxonomy as tax

    return {"categories": tax.INCIDENT_CATEGORIES, "severities": tax.SEVERITIES}


@router.get("/monitoring")
async def get_incident_monitoring(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    base_query = db.query(Incident)
    
    if current_user.role == "aggregator":
        from app.db.models.aggregator_profile import AggregatorProfile
        aggregator = db.query(AggregatorProfile).filter(AggregatorProfile.user_id == current_user.id).first()
        if not aggregator:
            raise HTTPException(status_code=403, detail="Not an aggregator")
        base_query = base_query.filter(Incident.aggregator_id == aggregator.id)
    
    elif current_user.role == "agent":
        crew_hpids, trip_ids = get_agent_incident_filters(current_user.id, db)
        if crew_hpids is None:
            return {
                "active_crew": 0,
                "active_aggregator": 0,
                "active_incidents": [],
                "resolved_incidents": []
            }
        from sqlalchemy import or_
        base_query = base_query.filter(
            or_(
                Incident.reporter_id.in_(crew_hpids),
                Incident.trip_id.in_(trip_ids)
            )
        )
    
    else:
        raise HTTPException(status_code=403, detail="Not authorized")

    active_incidents = base_query.filter(Incident.status.in_([IncidentStatus.ACTIVE, IncidentStatus.INVESTIGATING])).all()
    resolved_incidents = base_query.filter(Incident.status == IncidentStatus.RESOLVED).all()
    
    active_crew = sum(1 for inc in active_incidents if inc.type == IncidentType.CREW)
    active_aggregator = sum(1 for inc in active_incidents if inc.type == IncidentType.DRIVER) # Assuming DRIVER type represents aggregator incidents in this context as per original model

    return {
        "active_crew": active_crew,
        "active_aggregator": active_aggregator,
        "active_incidents": active_incidents,
        "resolved_incidents": resolved_incidents
    }

@router.get("/", response_model=List[IncidentResponse])
async def get_incidents(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.role == "aggregator":
        from app.db.models.aggregator_profile import AggregatorProfile
        aggregator = db.query(AggregatorProfile).filter(AggregatorProfile.user_id == current_user.id).first()
        if not aggregator:
            raise HTTPException(status_code=403, detail="Not an aggregator")
        return db.query(Incident).filter(Incident.aggregator_id == aggregator.id).all()
    
    elif current_user.role == "superadmin":
        return db.query(Incident).all()
    
    elif current_user.role == "agent":
        crew_hpids, trip_ids = get_agent_incident_filters(current_user.id, db)
        if crew_hpids is None:
            return []
        from sqlalchemy import or_
        return db.query(Incident).filter(
            or_(
                Incident.reporter_id.in_(crew_hpids),
                Incident.trip_id.in_(trip_ids)
            )
        ).all()
    
    else:
        raise HTTPException(status_code=403, detail="Not authorized to list incidents")

@router.post("/", response_model=IncidentResponse)
async def create_incident(
    incident_in: IncidentCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    from app.services import incident_taxonomy as tax

    incident_data = incident_in.model_dump()
    incident_id = f"INC-{uuid.uuid4().hex[:6].upper()}"

    # Validate the taxonomy before anything is written. An unknown category
    # would sail straight through to reports and quietly skew them.
    category = incident_data.get("category")
    sub_category = incident_data.get("sub_category")
    if category and not tax.is_valid_category(category):
        raise HTTPException(status_code=400, detail=f"Unknown incident category: {category}")
    if not tax.is_valid_sub_category(category, sub_category):
        raise HTTPException(
            status_code=400,
            detail=f"Sub-category {sub_category!r} does not belong to {category!r}",
        )

    # Crew never set severity — a person in trouble should not be grading their
    # own risk. Medical and Safety start High; the agent can adjust later.
    incident_data["severity"] = tax.default_severity_for(category)
    
    if current_user.role == "aggregator":
        from app.db.models.aggregator_profile import AggregatorProfile
        aggregator = db.query(AggregatorProfile).filter(AggregatorProfile.user_id == current_user.id).first()
        if not aggregator:
            raise HTTPException(status_code=403, detail="Not an aggregator")
        
        # Remove fields that we will set explicitly
        for field in ["aggregator_id"]:
            incident_data.pop(field, None)

        incident = Incident(
            **incident_data,
            aggregator_id=aggregator.id,
            incident_id=incident_id
        )
    elif current_user.role == "crew":
        from app.db.models.crew_profile import CrewProfile
        crew = db.query(CrewProfile).filter(CrewProfile.user_id == current_user.id).first()
        
        # Remove fields that we will set explicitly to avoid "multiple values for keyword argument"
        for field in ["reporter_name", "reporter_role", "reporter_id", "type", "port_name"]:
            incident_data.pop(field, None)

        reporter_hpid = crew.hpid if crew else None
        incident = Incident(
            **incident_data,
            incident_id=incident_id,
            reporter_name=current_user.name,
            reporter_role=crew.rank if crew else "Crew",
            reporter_id=reporter_hpid,
            port_name=crew.current_port if crew else None,
            # Resolved now rather than at read time, so the incident stays
            # findable even if the crew member later leaves the manifest.
            vessel_id=_resolve_vessel_for_reporter(db, reporter_hpid),
            type=IncidentType.CREW
        )
    else:
        raise HTTPException(status_code=403, detail="Not authorized to create incidents")
    
    db.add(incident)
    db.flush()
    _record_timeline(db, incident, "reported", "Incident Reported",
                     detail=f"Reported by {incident.reporter_name or 'crew'}.")
    _record_timeline(db, incident, "received", "Incident Received",
                     detail="Incident has been received and logged in the system.")
    db.commit()
    db.refresh(incident)
    return _serialize_incident(db, incident)

@router.get("/crew/recipients", response_model=List[dict])
async def get_incident_recipients(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.role != "crew":
        raise HTTPException(status_code=403, detail="Only crew can fetch recipients")
    
    from app.db.models.crew_profile import CrewProfile
    from app.db.models.aggregator_profile import AggregatorProfile
    from app.db.models.port import Port
    from sqlalchemy import or_
    
    crew = db.query(CrewProfile).filter(CrewProfile.user_id == current_user.id).first()
    if not crew or not crew.current_port:
        return [{"id": 0, "name": "General Support"}]
    
    aggregators = (
        db.query(AggregatorProfile)
        .join(Port, AggregatorProfile.operating_port_id == Port.id)
        .filter(
            or_(
                Port.code == crew.current_port,
                Port.name == crew.current_port,
            )
        )
        .all()
    )
    
    recipients = [{"id": 0, "name": "General Support"}]
    for agg in aggregators:
        recipients.append({
            "id": agg.id,
            "name": agg.company_name
        })
    
    return recipients

@router.get("/{id}", response_model=IncidentResponse)
async def get_incident(
    id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(Incident).filter(Incident.id == id)
    
    if current_user.role == "aggregator":
        from app.db.models.aggregator_profile import AggregatorProfile
        aggregator = db.query(AggregatorProfile).filter(AggregatorProfile.user_id == current_user.id).first()
        if not aggregator:
             raise HTTPException(status_code=403, detail="Not authorized")
        incident = query.filter(Incident.aggregator_id == aggregator.id).first()
    elif current_user.role == "superadmin":
        incident = query.first()
    elif current_user.role == "agent":
        crew_hpids, trip_ids = get_agent_incident_filters(current_user.id, db)
        if crew_hpids is None:
             raise HTTPException(status_code=403, detail="Not authorized")
        from sqlalchemy import or_
        incident = query.filter(
            or_(
                Incident.reporter_id.in_(crew_hpids),
                Incident.trip_id.in_(trip_ids)
            )
        ).first()
    else:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    return incident

class StatusUpdate(BaseModel):
    status: IncidentStatus

@router.patch("/{id}/status", response_model=IncidentResponse)
async def update_incident_status(
    id: int,
    status_update: StatusUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    incident = await get_incident(id, db, current_user)
    previous = incident.status
    incident.status = status_update.status

    now = datetime.utcnow()
    # Stamp the closing time so resolution duration can be reported without
    # inferring it from the timeline.
    if status_update.status == IncidentStatus.RESOLVED and not incident.resolved_at:
        incident.resolved_at = now
    if status_update.status == IncidentStatus.CANCELLED and not incident.cancelled_at:
        incident.cancelled_at = now
    # Reopening clears the closing stamps. Leaving them behind meant an open
    # incident still carried a resolved-at time, so it would report a
    # resolution duration for something that is not resolved.
    if status_update.status in (IncidentStatus.ACTIVE, IncidentStatus.INVESTIGATING):
        incident.resolved_at = None
        incident.cancelled_at = None

    if previous != status_update.status:
        labels = {
            IncidentStatus.ACTIVE: ("reported", "Reopened"),
            IncidentStatus.INVESTIGATING: ("investigating", "Under Investigation"),
            IncidentStatus.RESOLVED: ("resolved", "Incident Resolved"),
            IncidentStatus.CANCELLED: ("cancelled", "Incident Cancelled"),
        }
        event_type, label = labels.get(status_update.status, ("status", "Status changed"))
        _record_timeline(
            db, incident, event_type, label,
            detail=f"Status changed from {previous.value} to {status_update.status.value}.",
            source="agent",
            actor_name=getattr(current_user, "name", None),
        )

    db.commit()
    db.refresh(incident)
    return _serialize_incident(db, incident)

@router.post("/{id}/notes", response_model=IncidentNoteResponse)
async def add_incident_note(
    id: int,
    note_in: IncidentNoteBase,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    incident = await get_incident(id, db, current_user)
    
    note = IncidentNote(
        incident_id=incident.id,
        note=note_in.note,
        author_name=note_in.author_name or current_user.name
    )
    
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


# --- Crew Safety Center (agent) -------------------------------------------

@router.get("/agent/summary")
def agent_safety_summary(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """The four tiles on the Crew Safety Center landing page.

    Everything is limited to the agent's own vessels — an agent should not see
    another agency's incidents, the same rule applied to the dashboard,
    notifications and trips.
    """
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can view the safety summary")

    from app.db.models.crew_sos import CrewSos
    from app.db.models.crew_profile import CrewProfile

    hpids, _ = _agent_hpids_and_vessels(db, current_user.id)
    from app.services.port_time import agent_port_day
    today_start, today_end, _ = agent_port_day(db, current_user)

    active_sos = 0
    avg_response_seconds = None
    if hpids:
        crew_ids = [
            cp.id for cp in db.query(CrewProfile.id).filter(CrewProfile.hpid.in_(hpids)).all()
        ]
        if crew_ids:
            active_sos = db.query(CrewSos).filter(
                CrewSos.crew_profile_id.in_(crew_ids),
                CrewSos.closed_at.is_(None),
                CrewSos.cancelled_at.is_(None),
            ).count()

            # Agreed definition: SOS raised -> agent acknowledged.
            acked = db.query(CrewSos.created_at, CrewSos.acknowledged_at).filter(
                CrewSos.crew_profile_id.in_(crew_ids),
                CrewSos.acknowledged_at.isnot(None),
            ).all()
            deltas = [
                (a - c).total_seconds()
                for c, a in acked
                if c and a and a >= c
            ]
            if deltas:
                avg_response_seconds = int(sum(deltas) / len(deltas))

    open_incidents = investigating = resolved_today = 0
    ownership = _agent_incident_filter(db, current_user.id)
    if ownership is not None:
        base = db.query(Incident).filter(ownership)
        open_incidents = base.filter(Incident.status == IncidentStatus.ACTIVE).count()
        investigating = base.filter(Incident.status == IncidentStatus.INVESTIGATING).count()
        resolved_today = base.filter(
            Incident.status == IncidentStatus.RESOLVED,
            Incident.resolved_at.isnot(None),
            Incident.resolved_at >= today_start,
            Incident.resolved_at < today_end,
        ).count()

    return {
        "active_sos": active_sos,
        "open_incidents": open_incidents,
        "investigating_incidents": investigating,
        "resolved_today": resolved_today,
        "avg_response_seconds": avg_response_seconds,
    }


@router.get("/agent/list")
def agent_incident_list(
    status_filter: Optional[str] = None,
    vessel_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Incidents raised by crew on this agent's vessels."""
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can view these incidents")

    ownership = _agent_incident_filter(db, current_user.id)
    if ownership is None:
        return {"incidents": []}

    query = db.query(Incident).filter(ownership)
    if vessel_id is not None:
        query = query.filter(Incident.vessel_id == vessel_id)
    if status_filter:
        try:
            query = query.filter(Incident.status == IncidentStatus(status_filter.upper()))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown status: {status_filter}")

    rows = query.order_by(Incident.created_at.desc()).all()
    return {"incidents": [_serialize_incident(db, i) for i in rows]}


def _agent_incident_or_404(db: Session, agent_user_id: int, incident_id: int) -> Incident:
    """One incident, only if it belongs to this agent's crew.

    404 rather than 403 for someone else's incident, so ids cannot be probed —
    the same rule used for trips, shore passes and SOS.
    """
    ownership = _agent_incident_filter(db, agent_user_id)
    incident = None
    if ownership is not None:
        incident = (
            db.query(Incident)
            .filter(Incident.id == incident_id, ownership)
            .first()
        )
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.get("/agent/detail/{incident_id}")
def agent_incident_detail(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Everything the Incident Details screen shows, in one request.

    The screen needs the incident, its timeline, its notes and the crew member
    who raised it. Four round-trips for one screen is wasteful when the
    ownership check is identical for all four.
    """
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can view incident details")

    from app.db.models.crew_profile import CrewProfile
    from app.db.models.incident import IncidentTimelineEvent
    from app.db.models.user import User

    incident = _agent_incident_or_404(db, current_user.id, incident_id)

    events = (
        db.query(IncidentTimelineEvent)
        .filter(IncidentTimelineEvent.incident_id == incident.id)
        .order_by(IncidentTimelineEvent.event_time.asc(), IncidentTimelineEvent.id.asc())
        .all()
    )
    notes = (
        db.query(IncidentNote)
        .filter(IncidentNote.incident_id == incident.id)
        .order_by(IncidentNote.created_at.asc())
        .all()
    )

    reporter = None
    if incident.reporter_id:
        cp = db.query(CrewProfile).filter(CrewProfile.hpid == incident.reporter_id).first()
        if cp:
            # The phone number lives on the user account, not the crew profile.
            phone = db.query(User.mobile_number).filter(User.id == cp.user_id).first()
            reporter = {
                "hpid": cp.hpid,
                "full_name": cp.full_name,
                "rank": cp.rank,
                "nationality": cp.nationality,
                "phone": phone[0] if phone else None,
            }

    detail = _serialize_incident(db, incident)
    # Reported -> closed, when the incident has actually been closed. Left null
    # while it is open rather than counting up to "now", which would make an
    # open incident look like it had a resolution time.
    closed_at = incident.resolved_at or incident.cancelled_at
    resolution_seconds = None
    if closed_at and incident.created_at:
        elapsed = int((closed_at - incident.created_at).total_seconds())
        # A close stamped before the report is impossible; showing it would
        # render as a negative duration ("-20m"). Report nothing rather than
        # nonsense, and leave the bad row visible as bad rather than papering
        # over it with a zero.
        resolution_seconds = elapsed if elapsed >= 0 else None
    detail["resolution_seconds"] = resolution_seconds

    return {
        "incident": detail,
        "reporter": reporter,
        "timeline": [
            {
                "id": e.id,
                "source": e.source,
                "event_type": e.event_type,
                "label": e.label,
                "detail": e.detail,
                "actor_name": e.actor_name,
                "event_time": e.event_time,
            }
            for e in events
        ],
        "notes": [
            {
                "id": n.id,
                "author_name": n.author_name,
                "note": n.note,
                "created_at": n.created_at,
            }
            for n in notes
        ],
    }


@router.get("/{id}/timeline")
async def get_incident_timeline(
    id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """System and agent events for one incident, oldest first."""
    from app.db.models.incident import IncidentTimelineEvent

    incident = await get_incident(id, db, current_user)
    events = (
        db.query(IncidentTimelineEvent)
        .filter(IncidentTimelineEvent.incident_id == incident.id)
        .order_by(IncidentTimelineEvent.event_time.asc(), IncidentTimelineEvent.id.asc())
        .all()
    )
    return {
        "incident_id": incident.incident_id,
        "events": [
            {
                "id": e.id,
                "source": e.source,
                "event_type": e.event_type,
                "label": e.label,
                "detail": e.detail,
                "actor_name": e.actor_name,
                "event_time": e.event_time,
            }
            for e in events
        ],
    }
