# app/db/session.py
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
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

# A bounded connect attempt, so an unreachable database fails loudly.
#
# Without this, libpq waits on the OS default — well over a minute. The startup
# event runs several schema checks before the app can answer a health check, so
# a database that is merely slow to reach turned into "Waiting for application
# startup." and nothing else, until the platform gave up and rolled the deploy
# back. Ten seconds is far longer than a healthy connect and far shorter than a
# readiness probe's patience.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
    connect_args={"connect_timeout": 10},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def ddl_transaction(lock_timeout: str = "5s"):
    """A transaction that gives up rather than queue behind a table lock.

    `ALTER TABLE` needs an ACCESS EXCLUSIVE lock, and a rolling deploy keeps the
    previous container serving while the new one boots. One connection holding
    anything on the target table is enough to make the ALTER wait — with no
    lock_timeout, forever. That is what stalled a deploy in startup and had the
    platform roll it back; a retry minutes later succeeded only because those
    connections had gone.

    The startup guards already log and carry on when their DDL raises. A bounded
    wait is what lets them reach that handler: a blocked lock is not an
    exception, it is silence. Five seconds is generous for an uncontended lock,
    and the schema change is retried on the next boot either way.

    `set_config(..., is_local => true)` is `SET LOCAL` in function form, which
    unlike the `SET` statement accepts a bound parameter.
    """
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('lock_timeout', :timeout, true)"),
            {"timeout": lock_timeout},
        )
        yield connection


# ---- FastAPI dependency ----
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
