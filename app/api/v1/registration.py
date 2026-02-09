from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from datetime import date

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.crew_profile import CrewProfile
from app.services.auth import get_password_hash, create_access_token
from app.core.config import settings
from app.api.v1.routes_auth import AuthOut

router = APIRouter()

class CrewRegistrationIn(BaseModel):
    # User fields
    email: EmailStr
    password: str = Field(min_length=6)
    mobile_number: str
    
    # Profile fields
    full_name: str
    rank: str
    nationality: str
    passport_number: str
    date_of_birth: date

@router.post("/crew", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
def register_crew(body: CrewRegistrationIn, db: Session = Depends(get_db)):
    email = body.email.lower().strip()

    # Check if user already exists
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    # 1. Create User
    user = User(
        name=body.full_name,
        email=email,
        mobile_number=body.mobile_number,
        hashed_password=get_password_hash(body.password),
        role="crew"
    )
    db.add(user)
    db.flush()  # Get user.id without committing

    # 2. Create Crew Profile
    crew_profile = CrewProfile(
        user_id=user.id,
        full_name=body.full_name,
        rank=body.rank,
        nationality=body.nationality,
        passport_number=body.passport_number,
        date_of_birth=body.date_of_birth
    )
    db.add(crew_profile)
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    db.refresh(user)

    # 3. Issue Token
    token = create_access_token(
        subject=user.email,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    
    return AuthOut(access_token=token, role=user.role)
