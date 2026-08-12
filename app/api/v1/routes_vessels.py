from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew
from app.db.models.crew_profile import CrewProfile
from app.db.models.cab_booking import CabBooking
from app.db.models.shore_pass import ShorePass
from app.db.models.user import User
from app.api.v1.routes_auth import get_current_user
from app.services.crew_service import generate_hpid
from app.services.crew_reference import normalize_nationality, normalize_rank
import uuid

router = APIRouter()


def is_partnered_agency(agency_name: Optional[str]) -> bool:
    if not agency_name:
        return False
    clean = agency_name.strip().lower()
    return clean not in ["other", "others", "none", "n/a", "", "other agency"]

# --- Pydantic Schemas ---

class CrewMemberIn(BaseModel):
    name: str
    rank: str
    nationality: Optional[str] = None
    passport_number: str
    status: Optional[str] = "Pending"
    shore_pass_eligible: Optional[bool] = False
    shore_pass_valid_upto: Optional[datetime] = None

class CrewMemberOut(BaseModel):
    id: int
    name: str
    rank: str
    nationality: Optional[str] = None
    hp_id: Optional[str] = None
    passport_number: Optional[str] = None
    expiry_date: Optional[datetime] = None
    status: str
    shore_pass_eligible: bool
    shore_pass_valid_upto: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class EligibilityUpdateIn(BaseModel):
    shore_pass_eligible: bool

class CabBookingOut(BaseModel):
    id: int
    pickup_address: str
    drop_address: str
    status: str
    
    class Config:
        from_attributes = True

class CrewProfileOut(BaseModel):
    id: int
    name: str
    rank: str
    hp_id: Optional[str] = None
    status: str
    visits: List[str] = []
    bookings: List[CabBookingOut] = []

    class Config:
        from_attributes = True

class VesselIn(BaseModel):
    name: str
    imo_number: str
    vessel_type: str
    berth_assignment: Optional[str] = None
    flag: Optional[str] = None
    agency_name: Optional[str] = None
    crew_count: Optional[int] = 0
    total_crew: Optional[int] = 0
    eta: Optional[datetime] = None
    etd: Optional[datetime] = None
    status: Optional[str] = "Active"

import csv
import io

class ManifestCrewRowOut(BaseModel):
    name: str
    rank: Optional[str] = None
    nationality: Optional[str] = None
    passport_number: Optional[str] = None
    shore_pass_eligible: bool = False
    shore_pass_valid_upto: Optional[datetime] = None


class ManifestPreviewOut(BaseModel):
    count: int
    source: str
    warnings: List[str] = []
    crew: List[ManifestCrewRowOut] = []


class ManifestConfirmIn(BaseModel):
    crew: List[ManifestCrewRowOut]


def _agent_vessel_or_404(db: Session, vessel_id: int, current_user: User) -> Vessel:
    if current_user.role == "superadmin":
        vessel = db.query(Vessel).filter(Vessel.id == vessel_id).first()
    else:
        vessel = db.query(Vessel).filter(
            Vessel.id == vessel_id, Vessel.agent_id == current_user.id
        ).first()
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")
    return vessel


def _save_manifest_rows(db: Session, vessel: Vessel, rows, port: Optional[str]) -> int:
    """Upsert parsed manifest rows onto a vessel's crew list.

    Kept separate from parsing so the agent can review what was read before any
    of it is written. Matching is on passport number or generated HPID, so
    re-uploading a corrected manifest updates crew rather than duplicating them.
    """
    saved = 0
    for row in rows:
        name = (row.name or "").strip()
        if not name:
            continue
        passport_number = (row.passport_number or "").strip().upper() or None
        rank = normalize_rank(row.rank)
        try:
            nationality = normalize_nationality(row.nationality, strict=bool(row.nationality))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Crew member {name}: {exc}",
            ) from exc

        generated_hpid = generate_hpid(passport_number, nationality, port) if passport_number else None

        crew = None
        if passport_number or generated_hpid:
            conditions = []
            if passport_number:
                conditions.append(VesselCrew.passport_number == passport_number)
            if generated_hpid:
                conditions.append(VesselCrew.hp_id == generated_hpid)
            crew = db.query(VesselCrew).filter(
                VesselCrew.vessel_id == vessel.id, or_(*conditions)
            ).first()

        # The shore-pass expiry belongs to the vessel, so uploaded crew inherit
        # it rather than carrying whatever the spreadsheet happened to contain.
        valid_upto = vessel.shore_pass_valid_upto or row.shore_pass_valid_upto

        if not crew:
            crew = VesselCrew(
                vessel_id=vessel.id,
                name=name,
                rank=rank or "",
                nationality=nationality,
                hp_id=generated_hpid,
                passport_number=passport_number,
                status="Pending",
                shore_pass_eligible=row.shore_pass_eligible,
                shore_pass_valid_upto=valid_upto,
            )
            db.add(crew)
        else:
            crew.name = name
            crew.rank = rank or crew.rank
            crew.nationality = nationality
            # Never overwrite an HPID that already exists. An HPID is the
            # identity every other record points at — incidents, SOS, shore
            # passes, bookings all store it — so regenerating one on a
            # re-upload silently orphans that crew member's whole history while
            # they are still aboard.
            crew.hp_id = crew.hp_id or generated_hpid
            crew.passport_number = passport_number or crew.passport_number
            crew.shore_pass_eligible = row.shore_pass_eligible
            if valid_upto:
                crew.shore_pass_valid_upto = valid_upto

        profile = (
            db.query(CrewProfile).filter(CrewProfile.hpid == generated_hpid).first()
            if generated_hpid else None
        )
        if profile:
            crew.status = "Mapped"
            agency_name = vessel.agency_name
            if not agency_name and vessel.agent and getattr(vessel.agent, "agent_profile", None):
                agency_name = vessel.agent.agent_profile.agency_name
            if is_partnered_agency(agency_name):
                existing_pass = db.query(ShorePass).filter(
                    ShorePass.crew_profile_id == profile.id,
                    ShorePass.port_name == port,
                    ShorePass.vessel_name == vessel.name,
                ).first()
                if not existing_pass:
                    port_code = (port or "GEN").replace("port_", "")[:3].upper()
                    vessel_code = vessel.name.replace(" ", "")[:3].upper()
                    shore_pass_id = f"SP-{port_code}-{vessel_code}-{uuid.uuid4().hex[:4].upper()}"
                    port_display = (port or "General").replace("port_", "").replace("_", " ").title()
                    db.add(ShorePass(
                        crew_profile_id=profile.id,
                        agent_name=f"{port_display} Port Authority",
                        shore_pass_id=shore_pass_id,
                        port_name=port,
                        vessel_name=vessel.name,
                        is_verified=False,
                        status="pending",
                    ))
        db.flush()
        from app.services.historical_context import assignment_for_manifest

        assignment_for_manifest(db, vessel, crew, profile=profile)
        saved += 1

    db.commit()
    return saved


@router.post("/{vessel_id}/crew/manifest/preview", response_model=ManifestPreviewOut)
async def preview_crew_manifest(
    vessel_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read a manifest and report what was found, without saving anything.

    The agent confirms the list before it reaches the crew record, so a misread
    file — especially a scanned PDF — is caught before it does any damage.
    """
    from app.services.crew_manifest import ManifestError, parse_manifest

    vessel = _agent_vessel_or_404(db, vessel_id, current_user)
    data = await file.read()
    try:
        parsed = parse_manifest(data, file.filename or "")
    except ManifestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not parsed.crew:
        raise HTTPException(status_code=400, detail="No crew members were found in that file.")

    return ManifestPreviewOut(
        count=len(parsed.crew),
        source=parsed.source,
        warnings=parsed.warnings,
        crew=[ManifestCrewRowOut(**row.model_dump()) for row in parsed.crew],
    )


@router.post("/{vessel_id}/crew/manifest/confirm")
def confirm_crew_manifest(
    vessel_id: int,
    body: ManifestConfirmIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save the crew the agent reviewed on the preview screen."""
    vessel = _agent_vessel_or_404(db, vessel_id, current_user)
    if not body.crew:
        raise HTTPException(status_code=400, detail="No crew members to save.")

    agent_profile = getattr(current_user, "agent_profile", None)
    port = agent_profile.assigned_port if agent_profile else None
    saved = _save_manifest_rows(db, vessel, body.crew, port)
    return {"message": f"Saved {saved} crew member{'' if saved == 1 else 's'}.", "saved": saved}


@router.post("/{vessel_id}/crew/upload")
async def upload_crew_manifest(
    vessel_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Parse and save in one step. Kept for callers that skip the preview."""
    from app.services.crew_manifest import ManifestError, parse_manifest

    vessel = _agent_vessel_or_404(db, vessel_id, current_user)
    data = await file.read()
    try:
        parsed = parse_manifest(data, file.filename or "")
    except ManifestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    agent_profile = getattr(current_user, "agent_profile", None)
    port = agent_profile.assigned_port if agent_profile else None
    saved = _save_manifest_rows(db, vessel, parsed.crew, port)
    return {
        "message": f"Successfully parsed and loaded {saved} crew members.",
        "filename": file.filename,
    }


@router.get("/crew/{hp_id}/profile", response_model=CrewProfileOut)
def get_crew_profile(hp_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(VesselCrew)
    if current_user.role == "agent":
        query = query.join(Vessel, Vessel.id == VesselCrew.vessel_id).filter(
            Vessel.agent_id == current_user.id
        )
    elif current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Agent access required")
    v_crew = query.filter(VesselCrew.hp_id == hp_id).first()
    if not v_crew:
        raise HTTPException(status_code=404, detail="Crew member not found")
    
    c_profile = db.query(CrewProfile).filter(CrewProfile.hpid == hp_id).first()
    
    bookings = []
    visits = []
    if c_profile:
        bookings = db.query(CabBooking).filter(
            CabBooking.crew_id == c_profile.id
        ).order_by(CabBooking.created_at.desc(), CabBooking.id.desc()).all()
        # Filter shoreline history
        shore_passes = db.query(ShorePass).filter(
            ShorePass.crew_profile_id == c_profile.id
        ).order_by(ShorePass.created_at.desc(), ShorePass.id.desc()).all()
        visits = [sp.port_name for sp in shore_passes if sp.port_name]

    return {
        "id": v_crew.id,
        "name": v_crew.name,
        "rank": v_crew.rank,
        "hp_id": v_crew.hp_id,
        "status": v_crew.status,
        "visits": visits,
        "bookings": bookings
    }

class VesselOut(BaseModel):
    id: int
    name: str
    imo_number: str
    vessel_type: str
    berth_assignment: Optional[str] = None
    flag: Optional[str] = None
    agency_name: Optional[str] = None
    agent_id: Optional[int] = None
    crew_count: Optional[int] = 0
    total_crew: Optional[int] = 0
    eligible_crew_count: Optional[int] = 0
    crew_ashore_count: Optional[int] = 0
    eta: Optional[datetime] = None
    etd: Optional[datetime] = None
    status: str
    # One expiry for the whole crew of this port call; crew may override.
    shore_pass_valid_upto: Optional[datetime] = None

    class Config:
        from_attributes = True

class VesselPublicOut(BaseModel):
    id: int
    name: str
    agency_name: Optional[str] = "Other"
    has_partnered_agency: bool = False

    class Config:
        from_attributes = True

# --- Routes ---

@router.post("/", response_model=VesselOut, status_code=status.HTTP_201_CREATED)
def create_vessel(body: VesselIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role not in ["agent", "superadmin"]:
        raise HTTPException(status_code=403, detail="Not authorized to create vessels")
    
    c_count = body.crew_count if body.crew_count is not None else 0
    if body.total_crew is not None:
        c_count = body.total_crew

    resolved_agency = body.agency_name
    if not resolved_agency and current_user.role == "agent":
        if hasattr(current_user, "agent_profile") and current_user.agent_profile:
            resolved_agency = current_user.agent_profile.agency_name

    vessel = Vessel(
        agent_id=current_user.id,
        name=body.name,
        imo_number=body.imo_number,
        vessel_type=body.vessel_type,
        berth_assignment=body.berth_assignment,
        flag=body.flag,
        agency_name=resolved_agency,
        crew_count=c_count,
        eta=body.eta,
        etd=body.etd,
        status="Active"
    )
    db.add(vessel)
    try:
        db.flush()
        from app.services.historical_context import active_vessel_call
        from app.services.vessel_lifecycle import synchronize_vessel_lifecycle

        active_vessel_call(db, vessel)
        synchronize_vessel_lifecycle(db, [vessel])
        db.commit()
        db.refresh(vessel)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Vessel IMO possibly already exists")
    
    if not vessel.agency_name and vessel.agent and hasattr(vessel.agent, "agent_profile") and vessel.agent.agent_profile:
        vessel.agency_name = vessel.agent.agent_profile.agency_name
    
    return vessel

@router.patch("/{vessel_id}", response_model=VesselOut)
def update_vessel(vessel_id: int, body: VesselIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    vessel = db.query(Vessel).filter(Vessel.id == vessel_id).first()
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")
    
    if current_user.role == "agent" and vessel.agent_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this vessel")
        
    vessel.name = body.name
    vessel.imo_number = body.imo_number
    vessel.vessel_type = body.vessel_type
    vessel.berth_assignment = body.berth_assignment
    vessel.flag = body.flag
    if body.agency_name is not None:
        vessel.agency_name = body.agency_name
    
    c_count = body.crew_count if body.crew_count is not None else 0
    if body.total_crew is not None:
        c_count = body.total_crew
    vessel.crew_count = c_count
    
    vessel.eta = body.eta
    vessel.etd = body.etd
    from app.services.historical_context import refresh_active_vessel_call
    from app.services.vessel_lifecycle import synchronize_vessel_lifecycle

    refresh_active_vessel_call(db, vessel)
    synchronize_vessel_lifecycle(db, [vessel])
        
    try:
        db.commit()
        db.refresh(vessel)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail="Vessel IMO possibly already exists")
        
    if not vessel.agency_name and vessel.agent and hasattr(vessel.agent, "agent_profile") and vessel.agent.agent_profile:
        vessel.agency_name = vessel.agent.agent_profile.agency_name

    return vessel

@router.get("/", response_model=List[VesselOut])
def get_vessels(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can access their vessels")
    
    vessels = db.query(Vessel).filter(Vessel.agent_id == current_user.id).all()
    from app.services.vessel_lifecycle import synchronize_vessel_lifecycle

    if synchronize_vessel_lifecycle(db, vessels):
        db.commit()
    for v in vessels:
        if not v.agency_name and v.agent and hasattr(v.agent, "agent_profile") and v.agent.agent_profile:
            v.agency_name = v.agent.agent_profile.agency_name
    return vessels

@router.get("/public", response_model=List[VesselPublicOut])
def get_public_vessels(
    port_code: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    vessels = db.query(Vessel).all()
    out = []
    for v in vessels:
        agency = v.agency_name
        if not agency and v.agent and hasattr(v.agent, "agent_profile") and v.agent.agent_profile:
            agency = v.agent.agent_profile.agency_name
        if not agency:
            agency = "Other"
        
        has_partnered = is_partnered_agency(agency)
        out.append(VesselPublicOut(
            id=v.id,
            name=v.name,
            agency_name=agency,
            has_partnered_agency=has_partnered
        ))
    return out


@router.get("/history/calls")
def get_agent_vessel_call_history(
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Departed/archived calls remain visible after a vessel leaves the roster."""
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can access vessel history")
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(status_code=422, detail="Invalid history pagination")

    from app.db.models.agent_profile import AgentProfile
    from app.db.models.cab_booking import CabBooking
    from app.db.models.crew_sos import CrewSos
    from app.db.models.incident import Incident
    from app.db.models.report_snapshot import ReportSnapshot
    from app.db.models.vessel_call import VesselCall

    agency_id = db.query(AgentProfile.id).filter(
        AgentProfile.user_id == current_user.id
    ).scalar()
    if agency_id is None:
        return []

    calls = (
        db.query(VesselCall)
        .filter(
            VesselCall.agency_id == agency_id,
            or_(
                VesselCall.ended_at.isnot(None),
                VesselCall.status.in_(["DEPARTED", "ARCHIVED", "REASSIGNED"]),
            ),
        )
        .order_by(VesselCall.ended_at.desc(), VesselCall.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    call_ids = [call.id for call in calls]

    def _counts(model):
        if not call_ids:
            return {}
        return dict(
            db.query(model.vessel_call_id, func.count(model.id))
            .filter(model.vessel_call_id.in_(call_ids))
            .group_by(model.vessel_call_id)
            .all()
        )

    trip_counts = _counts(CabBooking)
    incident_counts = _counts(Incident)
    sos_counts = _counts(CrewSos)
    report_counts = _counts(ReportSnapshot)
    output = []
    for call in calls:
        output.append({
            "vessel_call_id": call.id,
            "vessel_id": call.vessel_id,
            "vessel_name": call.vessel_name,
            "imo_number": call.imo_number,
            "flag": call.flag,
            "port_name": call.port_name,
            "eta": call.eta,
            "etd": call.etd,
            "started_at": call.started_at,
            "ended_at": call.ended_at,
            "status": call.status,
            "trip_count": trip_counts.get(call.id, 0),
            "incident_count": incident_counts.get(call.id, 0),
            "sos_count": sos_counts.get(call.id, 0),
            "report_count": report_counts.get(call.id, 0),
        })
    return output

@router.get("/{vessel_id}", response_model=VesselOut)
def get_vessel_details(vessel_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    vessel = db.query(Vessel).filter(Vessel.id == vessel_id, Vessel.agent_id == current_user.id).first()
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")
    from app.services.vessel_lifecycle import synchronize_vessel_lifecycle

    if synchronize_vessel_lifecycle(db, [vessel]):
        db.commit()
        db.refresh(vessel)
    return vessel

@router.get("/{vessel_id}/crew", response_model=List[CrewMemberOut])
def get_crew_manifest(vessel_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Vessel).filter(Vessel.id == vessel_id)
    if current_user.role == "agent":
        query = query.filter(Vessel.agent_id == current_user.id)
    elif current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Only agents or superadmins can view crew manifests")
    vessel = query.first()
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")
    
    return vessel.crew_manifest

@router.post("/{vessel_id}/crew", response_model=CrewMemberOut, status_code=status.HTTP_201_CREATED)
def add_crew_member(vessel_id: int, body: CrewMemberIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    vessel = db.query(Vessel).filter(Vessel.id == vessel_id, Vessel.agent_id == current_user.id).first()
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")
    
    agent_profile = current_user.agent_profile
    port = agent_profile.assigned_port if agent_profile else None
    
    # Generate HPID based on Passport, Nationality, and Port
    try:
        nationality = normalize_nationality(body.nationality, strict=bool(body.nationality))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    generated_hpid = generate_hpid(body.passport_number, nationality, port)
    
    crew = VesselCrew(
        vessel_id=vessel.id,
        name=body.name,
        rank=normalize_rank(body.rank) or "other",
        nationality=nationality,
        hp_id=generated_hpid,
        passport_number=body.passport_number,
        status=body.status,
        shore_pass_eligible=body.shore_pass_eligible if body.shore_pass_eligible is not None else False,
        shore_pass_valid_upto=body.shore_pass_valid_upto
    )
    db.add(crew)
    db.flush()
    
    # Check if a matching CrewProfile exists to automatically generate a ShorePass
    profile = db.query(CrewProfile).filter(CrewProfile.hpid == generated_hpid).first()
    agency_name = vessel.agency_name
    if not agency_name and vessel.agent and hasattr(vessel.agent, "agent_profile") and vessel.agent.agent_profile:
        agency_name = vessel.agent.agent_profile.agency_name
    if profile and is_partnered_agency(agency_name):
        # Create ShorePass automatically
        port_code = (port or "GEN").replace("port_", "")[:3].upper()
        vessel_code = vessel.name.replace(" ", "")[:3].upper()
        random_suffix = uuid.uuid4().hex[:4].upper()
        shore_pass_id = f"SP-{port_code}-{vessel_code}-{random_suffix}"
        
        # Derive agent name
        port_display = (port or "General").replace("port_", "").replace("_", " ").title()
        agent_name = f"{port_display} Port Authority"
        
        new_pass = ShorePass(
            crew_profile_id=profile.id,
            agent_name=agent_name,
            shore_pass_id=shore_pass_id,
            port_name=port,
            vessel_name=vessel.name,
            is_verified=False,
            status="pending"
        )
        db.add(new_pass)
        print(f"DEBUG: Automated ShorePass created for {body.name} (HPID: {generated_hpid})")

    from app.services.historical_context import assignment_for_manifest

    assignment_for_manifest(db, vessel, crew, profile=profile)

    db.commit()
    db.refresh(crew)
    return crew

@router.patch("/{vessel_id}/crew/{crew_id}/eligibility", response_model=CrewMemberOut)
def update_crew_eligibility(
    vessel_id: int, 
    crew_id: int, 
    body: EligibilityUpdateIn, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    if current_user.role == "agent":
        vessel = db.query(Vessel).filter(Vessel.id == vessel_id, Vessel.agent_id == current_user.id).first()
        if not vessel:
            raise HTTPException(status_code=404, detail="Vessel not found or unauthorized")
    elif current_user.role == "superadmin":
        vessel = db.query(Vessel).filter(Vessel.id == vessel_id).first()
        if not vessel:
            raise HTTPException(status_code=404, detail="Vessel not found")
    else:
        raise HTTPException(status_code=403, detail="Only agents or superadmins can toggle eligibility")

    crew = db.query(VesselCrew).filter(VesselCrew.id == crew_id, VesselCrew.vessel_id == vessel.id).first()
    if not crew:
        raise HTTPException(status_code=404, detail="Crew member not found on this vessel")
    
    crew.shore_pass_eligible = body.shore_pass_eligible
    db.commit()
    db.refresh(crew)
    return crew

class ShorePassValidityIn(BaseModel):
    shore_pass_valid_upto: Optional[datetime] = None
    # False leaves crew who already have their own date untouched, so a
    # deliberate individual override is not silently undone.
    apply_to_all: bool = True


class ShorePassValidityOut(BaseModel):
    vessel_id: int
    shore_pass_valid_upto: Optional[datetime] = None
    crew_updated: int


class RosterUnlinkOut(BaseModel):
    action: str
    vessel_id: int
    crew_id: Optional[int] = None


@router.patch("/{vessel_id}/shore-pass-validity", response_model=ShorePassValidityOut)
def set_vessel_shore_pass_validity(
    vessel_id: int,
    body: ShorePassValidityIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Set one shore-pass expiry for the whole crew of this vessel.

    The date belongs to the port call, not to each person, so it is stored on
    the vessel and pushed down to the crew manifest. Individuals can still be
    given a different date afterwards through the per-crew endpoint; that
    override survives until the master date is applied again.
    """
    if current_user.role == "agent":
        vessel = db.query(Vessel).filter(
            Vessel.id == vessel_id, Vessel.agent_id == current_user.id
        ).first()
        if not vessel:
            raise HTTPException(status_code=404, detail="Vessel not found or unauthorized")
    elif current_user.role == "superadmin":
        vessel = db.query(Vessel).filter(Vessel.id == vessel_id).first()
        if not vessel:
            raise HTTPException(status_code=404, detail="Vessel not found")
    else:
        raise HTTPException(
            status_code=403,
            detail="Only agents or superadmins can set shore pass validity",
        )

    vessel.shore_pass_valid_upto = body.shore_pass_valid_upto

    crew_query = db.query(VesselCrew).filter(VesselCrew.vessel_id == vessel.id)
    if not body.apply_to_all:
        crew_query = crew_query.filter(VesselCrew.shore_pass_valid_upto.is_(None))

    crew_updated = crew_query.update(
        {VesselCrew.shore_pass_valid_upto: body.shore_pass_valid_upto},
        synchronize_session=False,
    )
    db.commit()

    return ShorePassValidityOut(
        vessel_id=vessel.id,
        shore_pass_valid_upto=body.shore_pass_valid_upto,
        crew_updated=crew_updated or 0,
    )


class CrewMemberUpdate(BaseModel):
    name: Optional[str] = None
    rank: Optional[str] = None
    nationality: Optional[str] = None
    passport_number: Optional[str] = None
    shore_pass_eligible: Optional[bool] = None
    shore_pass_valid_upto: Optional[datetime] = None

@router.patch("/{vessel_id}/crew/{crew_id}", response_model=CrewMemberOut)
def update_crew_member(
    vessel_id: int,
    crew_id: int,
    body: CrewMemberUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role == "agent":
        vessel = db.query(Vessel).filter(Vessel.id == vessel_id, Vessel.agent_id == current_user.id).first()
        if not vessel:
            raise HTTPException(status_code=404, detail="Vessel not found or unauthorized")
    elif current_user.role == "superadmin":
        vessel = db.query(Vessel).filter(Vessel.id == vessel_id).first()
        if not vessel:
            raise HTTPException(status_code=404, detail="Vessel not found")
    else:
        raise HTTPException(status_code=403, detail="Only agents or superadmins can update crew members")

    crew = db.query(VesselCrew).filter(VesselCrew.id == crew_id, VesselCrew.vessel_id == vessel.id).first()
    if not crew:
        raise HTTPException(status_code=404, detail="Crew member not found on this vessel")
    
    if body.name is not None:
        crew.name = body.name
    if body.rank is not None:
        crew.rank = normalize_rank(body.rank) or crew.rank
    if body.nationality is not None:
        try:
            crew.nationality = normalize_nationality(body.nationality, strict=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.passport_number is not None:
        crew.passport_number = body.passport_number.strip().upper()
    if body.shore_pass_eligible is not None:
        crew.shore_pass_eligible = body.shore_pass_eligible
    if body.shore_pass_valid_upto is not None:
        crew.shore_pass_valid_upto = body.shore_pass_valid_upto
        
    db.commit()
    db.refresh(crew)
    return crew


@router.delete("/{vessel_id}/assignment", response_model=RosterUnlinkOut)
def unlink_vessel_from_agent(
    vessel_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a vessel from an agent roster without deleting platform data."""
    if current_user.role != "agent":
        raise HTTPException(status_code=403, detail="Only agents can remove vessel assignments")

    vessel = db.query(Vessel).filter(
        Vessel.id == vessel_id,
        Vessel.agent_id == current_user.id,
    ).first()
    if not vessel:
        # Missing and somebody else's vessel are intentionally indistinguishable.
        raise HTTPException(status_code=404, detail="Vessel not found")

    from app.db.models.agent_roster_event import AgentRosterEvent
    from app.services.historical_context import finish_vessel_call

    db.add(AgentRosterEvent(
        actor_user_id=current_user.id,
        vessel_id=vessel.id,
        action="VESSEL_UNLINKED",
        subject_name=vessel.name,
    ))
    finish_vessel_call(db, vessel, status="ARCHIVED")
    vessel.agent_id = None
    db.commit()
    return RosterUnlinkOut(action="vessel_unlinked", vessel_id=vessel.id)


@router.delete("/{vessel_id}/crew/{crew_id}", response_model=RosterUnlinkOut)
def unlink_crew_from_vessel(
    vessel_id: int,
    crew_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove one manifest association while preserving account and history."""
    if current_user.role == "agent":
        vessel = db.query(Vessel).filter(
            Vessel.id == vessel_id,
            Vessel.agent_id == current_user.id,
        ).first()
    elif current_user.role == "superadmin":
        vessel = db.query(Vessel).filter(Vessel.id == vessel_id).first()
    else:
        raise HTTPException(
            status_code=403, detail="Only agents or superadmins can remove crew"
        )
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")

    crew = db.query(VesselCrew).filter(
        VesselCrew.id == crew_id,
        VesselCrew.vessel_id == vessel.id,
    ).first()
    if not crew:
        raise HTTPException(status_code=404, detail="Crew member not found")

    from app.db.models.agent_roster_event import AgentRosterEvent
    from app.services.historical_context import end_manifest_assignment

    db.add(AgentRosterEvent(
        actor_user_id=current_user.id,
        vessel_id=vessel.id,
        crew_manifest_id=crew.id,
        action="CREW_UNLINKED",
        subject_name=crew.name,
        subject_hpid=crew.hp_id,
    ))
    end_manifest_assignment(db, crew)
    db.delete(crew)
    db.commit()
    return RosterUnlinkOut(
        action="crew_unlinked", vessel_id=vessel.id, crew_id=crew_id
    )
