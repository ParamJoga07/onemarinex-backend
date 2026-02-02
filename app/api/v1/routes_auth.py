from datetime import timedelta
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Form,
    Header,
)
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
    # ensure these models are imported so relationships are configured
from app.db.models.user import User
from app.db.models.vendor_profile import VendorProfile
from app.services.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_subject,
)
from app.core.config import settings

router = APIRouter()


# ----------------------------
# Auth helpers / dependencies
# ----------------------------
def get_current_user(
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
) -> User:
    """
    Extract current user from Bearer token in the Authorization header.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    token = authorization.split(" ", 1)[1].strip()
    email = decode_subject(token)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


# ----------------------------
# Schemas
# ----------------------------
class SignupIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6)
    role: str = Field(pattern="^(shipping_company|vendor|agent)$")


class LoginIn(BaseModel):
    email: EmailStr
    password: str


# Unified auth response for both signup & login
class AuthOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


# ----------------------------
# Auth routes
# ----------------------------
@router.post("/signup", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    email = body.email.lower().strip()

    # enforce uniqueness
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        name=(body.name or "").strip() or None,
        email=email,
        hashed_password=get_password_hash(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # ⬇️ issue token immediately so user can continue onboarding
    token = create_access_token(
        subject=user.email,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return AuthOut(access_token=token, role=user.role)


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    email = body.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        subject=user.email,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return AuthOut(access_token=token, role=user.role)


# ----------------------------
# Vendor profile routes
# ----------------------------
@router.post("/vendor/profile", status_code=status.HTTP_201_CREATED)
async def create_vendor_profile(
    company_name: str = Form(...),
    contact_person: str = Form(...),
    phone_number: str = Form(...),
    ports_served: List[str] = Form([]),
    categories_supplied: List[str] = Form([]),
    logo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "vendor":
        raise HTTPException(status_code=403, detail="Only vendors can create profiles")

    # Ensure one profile per vendor (user_id is unique in the table)
    existing = db.query(VendorProfile).filter(VendorProfile.user_id == current_user.id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Vendor profile already exists")

    profile = VendorProfile(
        user_id=current_user.id,
        company_name=company_name,
        contact_person=contact_person,
        phone_number=phone_number,
        ports_served=ports_served,
        categories_supplied=categories_supplied,
        logo_url=f"/uploads/{logo.filename}" if logo else None,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return {"id": profile.id, "status": "created"}


@router.post("/vendor/documents")
async def upload_vendor_documents(
    trade_license: UploadFile | None = File(None),
    gst_vat: UploadFile | None = File(None),
    bank_details: UploadFile | None = File(None),
    iso_certifications: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "vendor":
        raise HTTPException(status_code=403, detail="Only vendors can upload vendor documents")

    profile = db.query(VendorProfile).filter(VendorProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Vendor profile not found")

    if trade_license:
        profile.trade_license_url = f"/uploads/{trade_license.filename}"
    if gst_vat:
        profile.gst_vat_url = f"/uploads/{gst_vat.filename}"
    if bank_details:
        profile.bank_details_url = f"/uploads/{bank_details.filename}"
    if iso_certifications:
        profile.iso_certifications_url = f"/uploads/{iso_certifications.filename}"

    db.commit()
    return {"status": "documents_uploaded"}


@router.get("/vendor/verification")
async def get_vendor_verification_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "vendor":
        raise HTTPException(status_code=403, detail="Only vendors can query verification status")

    profile = db.query(VendorProfile).filter(VendorProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Vendor profile not found")

    return {
        "status": profile.verification_status,
        "notes": profile.verification_notes,
    }
