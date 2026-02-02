#!/bin/bash

mkdir -p app/core app/db/models app/api/v1 app/services

# main.py
cat > app/main.py << 'EOF'
from fastapi import FastAPI
from app.api.v1 import routes_auth, routes_files, routes_contact

app = FastAPI(title="OneMarineX API")

# Include routers
app.include_router(routes_auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(routes_files.router, prefix="/api/v1/files", tags=["files"])
app.include_router(routes_contact.router, prefix="/api/v1/contact", tags=["contact"])

@app.get("/")
def root():
    return {"message": "Welcome to OneMarineX API"}
EOF

# core/config.py
cat > app/core/config.py << 'EOF'
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "OneMarineX API"
    DATABASE_URL: str = "postgresql+psycopg2://user:password@localhost:5432/onemarinex"
    SECRET_KEY: str = "supersecret"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REDIS_URL: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"

settings = Settings()
EOF

# core/security.py
cat > app/core/security.py << 'EOF'
from datetime import datetime, timedelta
from jose import jwt
from app.core.config import settings

def create_access_token(data: dict, expires_delta: int = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_delta or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
EOF

# db/base.py
cat > app/db/base.py << 'EOF'
from app.db.models import user, file_asset, password_reset
# Import all models here so Alembic can discover them
EOF

# db/session.py
cat > app/db/session.py << 'EOF'
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
EOF

# db/models/user.py
cat > app/db/models/user.py << 'EOF'
from sqlalchemy import Column, Integer, String, Boolean
from app.db.session import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
EOF

# db/models/file_asset.py
cat > app/db/models/file_asset.py << 'EOF'
from sqlalchemy import Column, Integer, String, ForeignKey
from app.db.session import Base

class FileAsset(Base):
    __tablename__ = "file_assets"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    path = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"))
EOF

# db/models/password_reset.py
cat > app/db/models/password_reset.py << 'EOF'
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime, timedelta
from app.db.session import Base

class PasswordReset(Base):
    __tablename__ = "password_resets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=1))
EOF

# api/v1/routes_auth.py
cat > app/api/v1/routes_auth.py << 'EOF'
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import create_access_token

router = APIRouter()

@router.post("/login")
def login(email: str, password: str, db: Session = Depends(get_db)):
    # Dummy authentication for now
    if email == "admin@example.com" and password == "password":
        token = create_access_token({"sub": email})
        return {"access_token": token, "token_type": "bearer"}
    return {"error": "Invalid credentials"}
EOF

# api/v1/routes_files.py
cat > app/api/v1/routes_files.py << 'EOF'
from fastapi import APIRouter, UploadFile, File

router = APIRouter()

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    return {"filename": file.filename}
EOF

# api/v1/routes_contact.py
cat > app/api/v1/routes_contact.py << 'EOF'
from fastapi import APIRouter

router = APIRouter()

@router.post("/")
def contact(name: str, email: str, message: str):
    return {"message": f"Thanks {name}, we received your message."}
EOF

# services/email.py
cat > app/services/email.py << 'EOF'
def send_email(to: str, subject: str, body: str):
    print(f"Sending email to {to}: {subject}")
EOF

# services/storage.py
cat > app/services/storage.py << 'EOF'
def upload_to_s3(file_name: str, file_content: bytes):
    print(f"Uploading {file_name} to S3 (dummy function)")
EOF

echo "✅ Project structure with starter FastAPI code created!"

