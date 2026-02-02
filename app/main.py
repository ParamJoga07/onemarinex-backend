# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.core.config import settings
from app.db.session import engine
from app.db.base import Base

from app.api.v1 import routes_auth, routes_contact, routes_files, routes_users
from app.api.v1.routes_vendor import router as vendor_router
from app.api.v1.routes_rfqs import router as rfq_router
from app.api.v1 import routes_quotes 
from app.api.v1 import routes_orders 

app = FastAPI(title=settings.APP_NAME)

# --- CORS config ---
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Startup event: ensure tables exist ---
@app.on_event("startup")
def on_startup():
    # Base is already linked to all models via app/db/base.py imports
    Base.metadata.create_all(bind=engine)

# --- Routes ---
app.include_router(routes_auth.router,    prefix="/api/v1/auth",    tags=["authentication"])
app.include_router(routes_contact.router, prefix="/api/v1/contact", tags=["contact"])
app.include_router(routes_files.router,   prefix="/api/v1/files",   tags=["files"])
app.include_router(routes_users.router,   prefix="/api/v1/users",   tags=["users"])
app.include_router(vendor_router,         prefix="/api/v1",         tags=["vendor"])
app.include_router(rfq_router, prefix="/api/v1", tags=["rfqs"])
app.include_router(routes_quotes.router, prefix="/api/v1", tags=["quotes"])
app.include_router(routes_orders.router,  prefix="/api/v1",         tags=["orders"])



# --- Health checks & root ---
@app.get("/")
def read_root():
    return {"message": "Welcome to OneMarinex API"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# --- Static uploads ---
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
