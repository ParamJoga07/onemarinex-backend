import io
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, String, or_
from typing import Optional
from datetime import datetime, timedelta, date as _date

from app.db.session import get_db
from app.db.models.agent_profile import AgentProfile
from app.db.models.vessel import Vessel
from app.db.models.cab_booking import CabBooking, BookingStatus
from app.db.models.incident import Incident, IncidentStatus
from app.db.models.shore_pass import ShorePass
from app.db.models.crew_sos import CrewSos
from app.db.models.crew_profile import CrewProfile
from app.db.models.vessel_crew import VesselCrew
from app.db.models.aggregator_profile import AggregatorProfile
from app.db.models.driver import Driver
from app.api.v1.routes_auth import get_current_user
from app.db.models.user import User
from pydantic import BaseModel, EmailStr
from typing import List, Dict, Any
from app.api.v1.routes_crew import ShorePassOut

router = APIRouter()

# --- Pydantic Schemas ---

class AgentProfileOut(BaseModel):
    id: int
    name: Optional[str]
    email: EmailStr
    mobile_number: Optional[str]
    agency_name: str
    contact_person: Optional[str]
    location: str
    assigned_port: Optional[str]
    gst_number: Optional[str]
    license_number: Optional[str]
    status: str
    profile_image: Optional[str]
    agency_logo_url: Optional[str] = None
    agent_identifier: Optional[str]
    auth_document_url: Optional[str] = None

    class Config:
        from_attributes = True

class AgentProfileUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    mobile_number: Optional[str] = None
    agency_name: Optional[str] = None
    contact_person: Optional[str] = None
    location: Optional[str] = None
    assigned_port: Optional[str] = None
    profile_image: Optional[str] = None

class DashboardStats(BaseModel):
    total_vessels: int
    vessels_this_week: int
    crew_in_shore: int
    active_trips: int
    todays_trips: int
    trips_in_progress: int
    open_incidents: int
    investigating_incidents: int
    closed_incidents: int
    # Unresolved SOS alerts from this agent's crew. Defaulted so an older
    # frontend build that does not know the field still parses the response.
    open_sos: int = 0

class DashboardVessel(BaseModel):
    id: int
    name: str
    imo_number: str
    status: str
    ongoing_trips_count: int
    crew_ashore_count: int
    incidents_count: int

class DashboardTrip(BaseModel):
    id: int
    crew_name: str
    vessel_name: str
    from_loc: str
    to_loc: str
    status: str

class DashboardData(BaseModel):
    stats: DashboardStats
    active_vessels: List[DashboardVessel]
    live_trips: List[DashboardTrip]

class ShorePassActionIn(BaseModel):
    rejection_reason: Optional[str] = None


# A trip that is happening right now. ON_TRIP/ARRIVED are the current statuses;
# IN_PROGRESS is the legacy spelling kept on older rows.
LIVE_TRIP_STATUSES = [
    BookingStatus.DRIVER_ASSIGNED,
    BookingStatus.DRIVER_ACCEPTED,
    BookingStatus.ARRIVED,
    BookingStatus.ON_TRIP,
    BookingStatus.IN_PROGRESS,
]


def _agent_scope(db: Session, agent_user_id: int) -> tuple[list[int], list[int]]:
    """Vessels this agent owns, and the crew profiles sailing on them.

    Everything on the agent dashboard must be limited to the agent's own ships.
    Crew are matched by HPID, which is the only link between a vessel's manifest
    (``vessel_crew``) and a registered crew account (``crew_profiles``).
    """
    vessel_ids = [v.id for v in db.query(Vessel.id).filter(Vessel.agent_id == agent_user_id).all()]
    if not vessel_ids:
        return [], []

    hp_ids = [
        c.hp_id
        for c in db.query(VesselCrew.hp_id).filter(VesselCrew.vessel_id.in_(vessel_ids)).all()
        if c.hp_id
    ]
    if not hp_ids:
        return vessel_ids, []

    crew_profile_ids = [
        cp.id for cp in db.query(CrewProfile.id).filter(CrewProfile.hpid.in_(hp_ids)).all()
    ]
    return vessel_ids, crew_profile_ids


# --- Routes ---

@router.get("/profile", response_model=AgentProfileOut)
def get_agent_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can access this profile")
    
    agent_profile = current_user.agent_profile
    if not agent_profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    
    return {
        "id": agent_profile.id,
        "name": current_user.name,
        "email": current_user.email,
        "mobile_number": current_user.mobile_number,
        "agency_name": agent_profile.agency_name,
        "contact_person": agent_profile.contact_person,
        "location": agent_profile.location,
        "assigned_port": agent_profile.assigned_port,
        "gst_number": agent_profile.gst_number,
        "license_number": agent_profile.license_number,
        "status": agent_profile.status,
        "profile_image": agent_profile.profile_image,
        "agency_logo_url": agent_profile.agency_logo_url,
        "agent_identifier": agent_profile.agent_identifier,
        "auth_document_url": agent_profile.auth_document_url
    }

@router.patch("/profile", response_model=AgentProfileOut)
def update_agent_profile(
    body: AgentProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can update this profile")
    
    agent_profile = current_user.agent_profile
    if not agent_profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    
    # Update User fields
    if body.name is not None:
        current_user.name = body.name
    if body.email is not None:
        current_user.email = body.email
    if body.mobile_number is not None:
        current_user.mobile_number = body.mobile_number
    
    # Update AgentProfile fields
    if body.agency_name is not None:
        agent_profile.agency_name = body.agency_name
    if body.contact_person is not None:
        agent_profile.contact_person = body.contact_person
    if body.location is not None:
        agent_profile.location = body.location
    if body.assigned_port is not None:
        agent_profile.assigned_port = body.assigned_port
    if body.profile_image is not None:
        agent_profile.profile_image = body.profile_image
        
    db.commit()
    db.refresh(current_user)
    db.refresh(agent_profile)
    
    return get_agent_profile(db, current_user)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


@router.post("/profile/image", response_model=AgentProfileOut)
async def upload_agent_image(
    kind: str = "profile",
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload the agent's profile picture, or the agency logo.

    `kind=profile` sets the contact person's avatar; `kind=logo` sets the
    agency logo used on the PDF reports. They are separate images and are
    stored in separate columns.

    There was previously no upload route at all, so the "Change Profile"
    button on the profile page had nothing to call.
    """
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can update this profile")

    agent_profile = current_user.agent_profile
    if not agent_profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    if kind not in {"profile", "logo"}:
        raise HTTPException(status_code=400, detail="kind must be 'profile' or 'logo'")

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Upload a JPEG, PNG, WebP or GIF image.",
        )

    # Read once so the size can be checked before anything is stored.
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image must be 5 MB or smaller.")
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    from app.services.storage import save_fileobj

    suffix = (file.filename or "").rsplit(".", 1)[-1].lower() or "jpg"
    key = f"agent_{kind}/{agent_profile.id}_{uuid.uuid4().hex[:8]}.{suffix}"
    stored = save_fileobj(io.BytesIO(data), key, content_type=file.content_type)

    if kind == "logo":
        agent_profile.agency_logo_url = stored
    else:
        agent_profile.profile_image = stored

    db.commit()
    db.refresh(agent_profile)
    return get_agent_profile(db, current_user)


@router.get("/dashboard", response_model=DashboardData)
def get_dashboard_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can access dashboard data")
    
    # 1. Stats
    vessels_query = db.query(Vessel).filter(Vessel.agent_id == current_user.id)
    total_vessels = vessels_query.count()
    
    # Vessels this week (simple approach: created in last 7 days)
    from datetime import timedelta
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    vessels_this_week = vessels_query.filter(Vessel.created_at >= seven_days_ago).count()
    
    # Active Vessels (Active + Departing — still in port)
    active_vessels_list = vessels_query.filter(Vessel.status.in_(["Active", "Departing"])).limit(5).all()
    
    # Every tile below is limited to this agent's own ships. Anything unscoped
    # reports the whole platform's activity, which is what made Crew Ashore and
    # Active Trips show the same number for every agent.
    vessel_ids, crew_profile_ids = _agent_scope(db, current_user.id)

    # Crew In Shore (active shore passes for agent's vessels)
    crew_in_shore = 0
    if crew_profile_ids:
        crew_in_shore = db.query(ShorePass).filter(
            ShorePass.crew_profile_id.in_(crew_profile_ids),
            ShorePass.in_time.is_(None),
        ).count()

    # Trips (Cab Bookings) — this agent's crew only.
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    todays_trips_count = 0
    trips_in_progress_count = 0
    active_trips_count = 0
    live_trips_data = []
    if crew_profile_ids:
        agent_trips = db.query(CabBooking).filter(CabBooking.crew_id.in_(crew_profile_ids))
        todays_trips_count = agent_trips.filter(CabBooking.created_at >= today_start).count()
        trips_in_progress_count = agent_trips.filter(
            CabBooking.created_at >= today_start,
            CabBooking.status.in_(LIVE_TRIP_STATUSES),
        ).count()
        # "Active trips" is every trip underway right now, regardless of the day
        # it was booked — an overnight trip is still active this morning.
        active_trips_count = agent_trips.filter(CabBooking.status.in_(LIVE_TRIP_STATUSES)).count()
        live_trips_data = agent_trips.filter(
            CabBooking.status.in_(LIVE_TRIP_STATUSES)
        ).order_by(CabBooking.created_at.desc()).limit(5).all()

    # Incidents raised by this agent's crew. Filtering by port would include
    # every other agency berthed at the same port.
    agent_hp_ids = [
        c.hp_id
        for c in db.query(VesselCrew.hp_id).filter(VesselCrew.vessel_id.in_(vessel_ids)).all()
        if c.hp_id
    ] if vessel_ids else []

    open_incidents = investigating_incidents = closed_incidents = 0
    if agent_hp_ids:
        agent_incidents = db.query(Incident).filter(Incident.reporter_id.in_(agent_hp_ids))
        open_incidents = agent_incidents.filter(Incident.status == IncidentStatus.ACTIVE).count()
        investigating_incidents = agent_incidents.filter(
            Incident.status == IncidentStatus.INVESTIGATING
        ).count()
        closed_incidents = agent_incidents.filter(
            Incident.status == IncidentStatus.RESOLVED
        ).count()

    # The tile is labelled "Open SOS/Incidents", so unresolved SOS alerts from
    # this agent's crew belong in it too. They were not counted at all before.
    open_sos = 0
    if crew_profile_ids:
        open_sos = db.query(CrewSos).filter(
            CrewSos.crew_profile_id.in_(crew_profile_ids),
            CrewSos.closed_at.is_(None),
            CrewSos.cancelled_at.is_(None),
        ).count()

    stats = DashboardStats(
        total_vessels=total_vessels,
        vessels_this_week=vessels_this_week,
        crew_in_shore=crew_in_shore,
        active_trips=active_trips_count,
        todays_trips=todays_trips_count,
        trips_in_progress=trips_in_progress_count,
        open_incidents=open_incidents,
        investigating_incidents=investigating_incidents,
        closed_incidents=closed_incidents,
        open_sos=open_sos,
    )

    vessels_data = []
    for v in active_vessels_list:
        # Get crew HPIDs for this vessel
        crew_hpids = [c.hp_id for c in db.query(VesselCrew).filter(VesselCrew.vessel_id == v.id).all() if c.hp_id]

        vessel_crew_ids = []
        if crew_hpids:
            vessel_crew_ids = [
                cp.id for cp in db.query(CrewProfile.id).filter(CrewProfile.hpid.in_(crew_hpids)).all()
            ]

        # 1. Ongoing Trips
        ongoing_trips = 0
        if vessel_crew_ids:
            ongoing_trips = db.query(CabBooking).filter(
                CabBooking.crew_id.in_(vessel_crew_ids),
                CabBooking.status.in_(LIVE_TRIP_STATUSES),
            ).count()

        # 2. Crew Ashore
        crew_ashore = 0
        if vessel_crew_ids:
            crew_ashore = db.query(ShorePass).filter(
                ShorePass.crew_profile_id.in_(vessel_crew_ids),
                ShorePass.in_time.is_(None)
            ).count()

        # 3. SOS/Incidents of ship — the card says "SOS/Incidents", so count both.
        incidents = 0
        if crew_hpids:
            incidents = db.query(Incident).filter(
                Incident.reporter_id.in_(crew_hpids),
                Incident.status.in_([IncidentStatus.ACTIVE, IncidentStatus.INVESTIGATING])
            ).count()
        if vessel_crew_ids:
            incidents += db.query(CrewSos).filter(
                CrewSos.crew_profile_id.in_(vessel_crew_ids),
                CrewSos.closed_at.is_(None),
                CrewSos.cancelled_at.is_(None),
            ).count()

        vessels_data.append(
            DashboardVessel(
                id=v.id,
                name=v.name,
                imo_number=v.imo_number,
                status=v.status,
                ongoing_trips_count=ongoing_trips,
                crew_ashore_count=crew_ashore,
                incidents_count=incidents
            )
        )

    # live_trips was previously computed and then discarded, so the dashboard's
    # live trips list was always empty. Resolve crew and vessel names for it.
    trips_data = []
    if live_trips_data:
        trip_crew_ids = {b.crew_id for b in live_trips_data if b.crew_id}
        crew_rows = db.query(CrewProfile).filter(CrewProfile.id.in_(trip_crew_ids)).all() if trip_crew_ids else []
        crew_by_id = {cp.id: cp for cp in crew_rows}

        vessel_name_by_hpid = {}
        hpids = [cp.hpid for cp in crew_rows if cp.hpid]
        if hpids:
            for vc, vessel_name in (
                db.query(VesselCrew.hp_id, Vessel.name)
                .join(Vessel, Vessel.id == VesselCrew.vessel_id)
                .filter(VesselCrew.hp_id.in_(hpids), Vessel.agent_id == current_user.id)
                .all()
            ):
                vessel_name_by_hpid[vc] = vessel_name

        for b in live_trips_data:
            crew = crew_by_id.get(b.crew_id)
            trips_data.append(
                DashboardTrip(
                    id=b.id,
                    crew_name=(crew.full_name if crew else None) or "Unknown crew",
                    vessel_name=vessel_name_by_hpid.get(crew.hpid if crew else None) or "—",
                    from_loc=b.pickup_address or "—",
                    to_loc=b.drop_address or "—",
                    status=b.status.value if hasattr(b.status, "value") else str(b.status),
                )
            )

    return DashboardData(
        stats=stats,
        active_vessels=vessels_data,
        live_trips=trips_data,
    )

@router.get("/shore-pass-requests", response_model=List[ShorePassOut])
def get_shore_pass_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can access shore pass requests")
    
    # Scoped to the agent's own vessels. Filtering by port showed — and let the
    # agent act on — shore passes belonging to every other agency berthed at
    # the same port.
    _, crew_profile_ids = _agent_scope(db, current_user.id)
    if not crew_profile_ids:
        return []

    requests = db.query(ShorePass).filter(
        ShorePass.crew_profile_id.in_(crew_profile_ids)
    ).order_by(ShorePass.created_at.desc()).all()

    return requests


def _agent_shore_pass_or_404(db: Session, request_id: int, current_user: User) -> ShorePass:
    """A shore pass belonging to this agent's crew, or a 404.

    Approve and reject previously looked the pass up by id with no ownership
    check at all, so any agent could grant or refuse shore leave for another
    agency's crew. 404 rather than 403 so ids cannot be probed.
    """
    shore_pass = db.query(ShorePass).filter(ShorePass.id == request_id).first()
    if not shore_pass:
        raise HTTPException(status_code=404, detail="Shore pass request not found")

    _, crew_profile_ids = _agent_scope(db, current_user.id)
    if shore_pass.crew_profile_id not in crew_profile_ids:
        raise HTTPException(status_code=404, detail="Shore pass request not found")
    return shore_pass

@router.post("/shore-pass-requests/{request_id}/approve", response_model=ShorePassOut)
def approve_shore_pass(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can approve shore passes")

    shore_pass = _agent_shore_pass_or_404(db, request_id, current_user)
    
    shore_pass.status = "approved"
    shore_pass.is_verified = True
    shore_pass.approved_by_id = current_user.id
    
    try:
        db.commit()
        db.refresh(shore_pass)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
        
    return shore_pass

@router.post("/shore-pass-requests/{request_id}/reject", response_model=ShorePassOut)
def reject_shore_pass(
    request_id: int,
    body: ShorePassActionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can reject shore passes")

    shore_pass = _agent_shore_pass_or_404(db, request_id, current_user)
    
    shore_pass.status = "rejected"
    shore_pass.rejection_reason = body.rejection_reason
    shore_pass.approved_by_id = current_user.id
    
    try:
        db.commit()
        db.refresh(shore_pass)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
        
    return shore_pass


# --- Helper: get crew profile IDs for an agent's vessels ---

def _get_agent_crew_profile_ids(db: Session, agent_user_id: int) -> list[int]:
    """Return crew_profile IDs for all crew mapped to the agent's vessels."""
    vessel_ids = [v.id for v in db.query(Vessel).filter(Vessel.agent_id == agent_user_id).all()]
    if not vessel_ids:
        return []
    crew_hpids = [
        c.hp_id for c in db.query(VesselCrew).filter(
            VesselCrew.vessel_id.in_(vessel_ids),
            VesselCrew.hp_id.isnot(None),
        ).all()
        if c.hp_id
    ]
    if not crew_hpids:
        return []
    return [
        cp.id for cp in db.query(CrewProfile).filter(CrewProfile.hpid.in_(crew_hpids)).all()
    ]


def _get_agent_crew_hpids(db: Session, agent_user_id: int) -> list[str]:
    """Return HPIDs for all crew mapped to the agent's vessels."""
    vessel_ids = [v.id for v in db.query(Vessel).filter(Vessel.agent_id == agent_user_id).all()]
    if not vessel_ids:
        return []
    return [
        c.hp_id for c in db.query(VesselCrew).filter(
            VesselCrew.vessel_id.in_(vessel_ids),
            VesselCrew.hp_id.isnot(None),
        ).all()
        if c.hp_id
    ]


# --- Agent Bookings ---

@router.get("/bookings")
def get_agent_bookings(
    status_filter: Optional[str] = None,
    provider_type: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can access agent bookings")

    crew_profile_ids = _get_agent_crew_profile_ids(db, current_user.id)
    if not crew_profile_ids:
        return []

    status_labels = {
        "pending_provider_response": "Pending Provider Response",
        "provider_accepted": "Provider Accepted",
        "provider_rejected": "Provider Rejected",
        "driver_assigned": "Driver Assigned",
        "driver_accepted": "Driver Accepted",
        "on_trip": "On Trip",
        "completed": "Completed",
        "cancelled": "Cancelled",
        "pending": "Pending",
        "confirmed": "Confirmed",
        "arrived": "Arrived",
        "in_progress": "In Progress",
    }
    ride_type_labels = {
        "flexible_ride": "Flexible Ride",
        "guaranteed_coordinated_ride": "Guaranteed Coordinated Ride",
    }

    query = db.query(
        CabBooking.id,
        CabBooking.booking_id,
        cast(CabBooking.ride_type, String).label("ride_type"),
        CabBooking.port,
        CabBooking.pickup_address,
        CabBooking.drop_address,
        cast(CabBooking.vehicle_type, String).label("vehicle_type"),
        CabBooking.vehicle_name,
        CabBooking.vehicle_category,
        CabBooking.estimated_price,
        CabBooking.num_passengers,
        cast(CabBooking.status, String).label("status"),
        CabBooking.provider_id,
        CabBooking.aggregator_id,
        CabBooking.aggregator_name,
        CabBooking.provider_response_status,
        CabBooking.provider_response_at,
        CabBooking.assigned_driver_id,
        CabBooking.driver_id,
        CabBooking.driver_name,
        CabBooking.driver_phone,
        CabBooking.driver_plate,
        CabBooking.driver_assigned_at,
        CabBooking.driver_accepted_at,
        CabBooking.trip_started_at,
        CabBooking.started_at,
        CabBooking.trip_completed_at,
        CabBooking.completed_at,
        CabBooking.otp,
        CabBooking.helpline_number,
        CabBooking.agent_number,
        CabBooking.scheduled_time,
        CabBooking.created_at,
        CabBooking.updated_at,
        CrewProfile.id.label("crew_id"),
        CrewProfile.full_name.label("crew_name"),
        CrewProfile.hpid.label("crew_hpid"),
        CrewProfile.vessel.label("crew_vessel"),
        AggregatorProfile.company_name.label("provider_company_name"),
        AggregatorProfile.provider_type.label("provider_type"),
        Driver.name.label("assigned_driver_name"),
        Driver.phone.label("assigned_driver_phone"),
        Driver.vehicle_number.label("assigned_driver_vehicle_number"),
    )
    query = query.outerjoin(CrewProfile, CabBooking.crew_id == CrewProfile.id)
    query = query.outerjoin(
        AggregatorProfile,
        or_(
            CabBooking.provider_id == AggregatorProfile.id,
            CabBooking.aggregator_id == AggregatorProfile.id,
        ),
    )
    query = query.outerjoin(Driver, CabBooking.assigned_driver_id == Driver.id)

    # Filter to only bookings by crew mapped under this agent
    query = query.filter(CabBooking.crew_id.in_(crew_profile_ids))

    if status_filter:
        query = query.filter(cast(CabBooking.status, String) == status_filter.lower())
    if provider_type:
        query = query.filter(AggregatorProfile.provider_type == provider_type)
    if date_from:
        query = query.filter(CabBooking.created_at >= date_from)
    if date_to:
        query = query.filter(CabBooking.created_at <= date_to)

    bookings = query.order_by(CabBooking.created_at.desc()).all()

    response: List[Dict[str, Any]] = []
    for booking in bookings:
        status_value = (booking.status or "").lower() if booking.status else None
        ride_type_value = (booking.ride_type or "").lower() if booking.ride_type else None
        response.append(
            {
                "id": booking.id,
                "booking_id": booking.booking_id,
                "ride_type": ride_type_value,
                "ride_type_label": ride_type_labels.get(ride_type_value),
                "port": booking.port,
                "crew": {
                    "id": booking.crew_id,
                    "name": booking.crew_name,
                    "hp_id": booking.crew_hpid,
                    "vessel": booking.crew_vessel,
                },
                "pickup_address": booking.pickup_address,
                "drop_address": booking.drop_address,
                "vehicle_type": (booking.vehicle_type or "").lower() if booking.vehicle_type else None,
                "vehicle_name": booking.vehicle_name,
                "vehicle_category": booking.vehicle_category,
                "estimated_price": float(booking.estimated_price) if booking.estimated_price else 0,
                "num_passengers": booking.num_passengers,
                "status": status_value,
                "status_label": status_labels.get(status_value, booking.status),
                "provider_id": booking.provider_id or booking.aggregator_id,
                "provider_name": booking.provider_company_name or booking.aggregator_name,
                "provider_type": booking.provider_type,
                "provider_response_status": booking.provider_response_status,
                "provider_response_at": booking.provider_response_at,
                "assigned_driver_id": booking.assigned_driver_id or booking.driver_id,
                "driver_name": booking.driver_name or booking.assigned_driver_name,
                "driver_phone": booking.driver_phone or booking.assigned_driver_phone,
                "driver_plate": booking.driver_plate or booking.assigned_driver_vehicle_number,
                "driver_assigned_at": booking.driver_assigned_at,
                "driver_accepted_at": booking.driver_accepted_at,
                "trip_started_at": booking.trip_started_at or booking.started_at,
                "trip_completed_at": booking.trip_completed_at or booking.completed_at,
                "otp": booking.otp,
                "helpline_number": booking.helpline_number or booking.agent_number,
                "scheduled_time": booking.scheduled_time,
                "created_at": booking.created_at,
                "updated_at": booking.updated_at,
            }
        )
    return response


# --- Agent: View Crew by HPID ---

class AgentCrewDetailOut(BaseModel):
    id: int
    full_name: str
    rank: str
    nationality: Optional[str]
    passport_number: Optional[str]
    date_of_birth: Optional[_date]
    hpid: Optional[str]
    current_port: Optional[str]
    vessel: Optional[str]
    vessel_id: Optional[int] = None
    vessel_name: Optional[str] = None
    imo_number: Optional[str] = None
    vessel_type: Optional[str] = None
    status: str = "Unmapped"
    shore_pass_eligible: bool = False
    expiry_date: Optional[_date] = None
    mapping_status: Optional[str] = None
    shore_pass_status: Optional[str] = None
    shore_pass_id: Optional[int] = None
    shore_pass_out_time: Optional[datetime] = None
    shore_pass_in_time: Optional[datetime] = None
    shore_pass_expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.get("/crew/{hp_id}", response_model=AgentCrewDetailOut)
def get_agent_crew_detail(
    hp_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can access this")

    # Find the VesselCrew record for this HPID on one of the agent's vessels
    vessel_crew = db.query(VesselCrew).filter(VesselCrew.hp_id == hp_id).first()
    vessel = None
    if vessel_crew:
        vessel = db.query(Vessel).filter(
            Vessel.id == vessel_crew.vessel_id,
            Vessel.agent_id == current_user.id
        ).first()
    if not vessel_crew or not vessel:
        raise HTTPException(status_code=404, detail="Crew not found in your vessels")

    crew_profile = db.query(CrewProfile).filter(CrewProfile.hpid == hp_id).first()

    shore_pass = None
    if crew_profile:
        shore_pass = db.query(ShorePass).filter(
            ShorePass.crew_profile_id == crew_profile.id
        ).order_by(ShorePass.created_at.desc()).first()

    full_name = crew_profile.full_name if crew_profile else vessel_crew.name
    rank = crew_profile.rank if crew_profile else vessel_crew.rank
    nationality = crew_profile.nationality if crew_profile else vessel_crew.nationality
    passport_number = crew_profile.passport_number if crew_profile else None
    date_of_birth = crew_profile.date_of_birth if crew_profile else None

    return AgentCrewDetailOut(
        id=crew_profile.id if crew_profile else vessel_crew.id,
        full_name=full_name,
        rank=rank,
        nationality=nationality,
        passport_number=passport_number,
        date_of_birth=date_of_birth,
        hpid=hp_id,
        current_port=crew_profile.current_port if crew_profile else None,
        vessel=crew_profile.vessel if crew_profile else vessel.name,
        vessel_id=vessel_crew.vessel_id,
        vessel_name=vessel.name,
        imo_number=vessel.imo_number,
        vessel_type=vessel.vessel_type,
        status=vessel_crew.status,
        shore_pass_eligible=vessel_crew.shore_pass_eligible,
        expiry_date=vessel_crew.expiry_date,
        mapping_status=vessel_crew.status,
        shore_pass_status=shore_pass.status if shore_pass else None,
        shore_pass_id=shore_pass.id if shore_pass else None,
        shore_pass_out_time=shore_pass.out_time if shore_pass else None,
        shore_pass_in_time=shore_pass.in_time if shore_pass else None,
        shore_pass_expires_at=shore_pass.expires_at if shore_pass else None,
    )


# --- Reports (K) -----------------------------------------------------------

class ShoreLeaveReportOut(BaseModel):
    """Everything the Shore Leave Operation Report prints.

    Rendered and printed in the browser rather than generated server-side: no
    new dependency, nothing to host, and the preview the agent checks is the
    exact thing that prints. The stamp and signature are added by hand, so the
    layout leaves space rather than trying to reproduce them.
    """
    vessel_name: str
    imo_number: Optional[str] = None
    berth: Optional[str] = None
    port_name: Optional[str] = None
    agency_name: Optional[str] = None
    agency_logo_url: Optional[str] = None
    report_date: str
    generated_at: datetime

    crew_onboard: int
    eligible_for_shore_leave: int
    crew_went_ashore: int
    completed_trips: int
    average_duration_minutes: Optional[int] = None
    returned_safely: int
    still_ashore: int
    sos_raised: int
    incidents_reported: int

    all_returned: bool
    incidents: List[Dict[str, Any]] = []


@router.get("/reports/shore-leave/{vessel_id}", response_model=ShoreLeaveReportOut)
def shore_leave_report(
    vessel_id: int,
    report_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Figures for one vessel's shore leave on one day."""
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can generate reports")

    vessel = db.query(Vessel).filter(
        Vessel.id == vessel_id, Vessel.agent_id == current_user.id
    ).first()
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")

    if report_date:
        try:
            day = datetime.strptime(report_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="report_date must be YYYY-MM-DD")
    else:
        day = datetime.utcnow()
    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    manifest = db.query(VesselCrew).filter(VesselCrew.vessel_id == vessel.id).all()
    hp_ids = [c.hp_id for c in manifest if c.hp_id]
    crew_profile_ids = [
        cp.id for cp in db.query(CrewProfile.id).filter(CrewProfile.hpid.in_(hp_ids)).all()
    ] if hp_ids else []

    passes = db.query(ShorePass).filter(
        ShorePass.crew_profile_id.in_(crew_profile_ids),
        ShorePass.out_time >= day_start,
        ShorePass.out_time < day_end,
    ).all() if crew_profile_ids else []

    returned = [p for p in passes if p.in_time]
    # Averaged over completed shore leaves only — including people still ashore
    # would drag the average down and misrepresent the day.
    durations = [
        (p.in_time - p.out_time).total_seconds() / 60
        for p in returned if p.in_time and p.out_time
    ]

    completed_trips = db.query(CabBooking).filter(
        CabBooking.crew_id.in_(crew_profile_ids),
        CabBooking.status == BookingStatus.COMPLETED,
        CabBooking.created_at >= day_start,
        CabBooking.created_at < day_end,
    ).count() if crew_profile_ids else 0

    sos_raised = db.query(CrewSos).filter(
        CrewSos.crew_profile_id.in_(crew_profile_ids),
        CrewSos.created_at >= day_start,
        CrewSos.created_at < day_end,
    ).count() if crew_profile_ids else 0

    day_incidents = db.query(Incident).filter(
        Incident.reporter_id.in_(hp_ids),
        Incident.created_at >= day_start,
        Incident.created_at < day_end,
    ).all() if hp_ids else []

    from app.services import incident_taxonomy as tax

    agent_profile = current_user.agent_profile
    still_ashore = len(passes) - len(returned)

    return ShoreLeaveReportOut(
        vessel_name=vessel.name,
        imo_number=vessel.imo_number,
        berth=vessel.berth_assignment,
        port_name=(vessel.agent.agent_profile.assigned_port
                   if vessel.agent and getattr(vessel.agent, "agent_profile", None) else None),
        agency_name=agent_profile.agency_name if agent_profile else vessel.agency_name,
        agency_logo_url=agent_profile.agency_logo_url if agent_profile else None,
        report_date=day_start.strftime("%Y-%m-%d"),
        generated_at=datetime.utcnow(),
        crew_onboard=len(manifest),
        eligible_for_shore_leave=sum(1 for c in manifest if c.shore_pass_eligible),
        crew_went_ashore=len(passes),
        completed_trips=completed_trips,
        average_duration_minutes=int(sum(durations) / len(durations)) if durations else None,
        returned_safely=len(returned),
        still_ashore=still_ashore,
        sos_raised=sos_raised,
        incidents_reported=len(day_incidents),
        # Drives the "operation successfully completed" checklist. Anyone still
        # ashore means the day is not closed out, whatever else looks fine.
        all_returned=still_ashore == 0,
        incidents=[
            {
                "incident_id": i.incident_id,
                "category": tax.category_label(i.category),
                "status": i.status.value if hasattr(i.status, "value") else str(i.status),
                "summary": i.title,
            }
            for i in day_incidents
        ],
    )
