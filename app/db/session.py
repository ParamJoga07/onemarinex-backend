# app/db/session.py
from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings


def _resolve_database_url() -> str:
    """
    Resolve the database URL.

    Priority:
      1. settings.DATABASE_URL (preferred)
      2. settings.SQLALCHEMY_DATABASE_URI (fallback)
      3. Build from DB_* env/config parts (DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_DATABASE, DB_SSL)
    """
    # 1) Full URL directly from settings
    url = getattr(settings, "DATABASE_URL", None)
    if url:
        return url

    # 2) Alternate naming some projects use
    url = getattr(settings, "SQLALCHEMY_DATABASE_URI", None)
    if url:
        return url

    # 3) Build from parts (common for Postgres)
    user = getattr(settings, "DB_USER", os.getenv("DB_USER"))
    password = getattr(settings, "DB_PASSWORD", os.getenv("DB_PASSWORD"))
    host = getattr(settings, "DB_HOST", os.getenv("DB_HOST", "localhost"))
    port = getattr(settings, "DB_PORT", os.getenv("DB_PORT", 5432))
    database = getattr(settings, "DB_DATABASE", os.getenv("DB_DATABASE", "postgres"))
    ssl = getattr(settings, "DB_SSL", os.getenv("DB_SSL", "false"))

    if not user or not password:
        raise RuntimeError(
            "Database URL not configured. "
            "Set settings.DATABASE_URL or provide DB_USER/DB_PASSWORD/DB_HOST/DB_PORT/DB_DATABASE."
        )

    sslmode = "require" if str(ssl).lower() in ("1", "true", "yes") else "disable"
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}?sslmode={sslmode}"


# ---- Engine & Session ----
DATABASE_URL = _resolve_database_url()
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# ---- FastAPI dependency ----
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
