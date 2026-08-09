from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.models import OAuthFlows as OAuthFlowsModel
from fastapi.openapi.utils import get_openapi
import logging
import logging.handlers
import os
from sqlalchemy import inspect, text
from apscheduler.schedulers.background import BackgroundScheduler

# --- Logging ---
# Without this, every logger.warning/exception in the app (notably the
# WhatsApp send failures) goes only to the console of whoever started the
# server, which makes production issues effectively invisible. Mirror all
# logs to a rotating file as well.
os.makedirs("logs", exist_ok=True)
_log_formatter = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)
_file_handler = logging.handlers.RotatingFileHandler(
    "logs/app.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_file_handler.setFormatter(_log_formatter)

_root_logger = logging.getLogger()
if not any(
    isinstance(h, logging.handlers.RotatingFileHandler)
    for h in _root_logger.handlers
):
    _root_logger.addHandler(_file_handler)
if _root_logger.level == logging.NOTSET or _root_logger.level > logging.INFO:
    _root_logger.setLevel(logging.INFO)

from app.core.config import settings
from app.db.session import engine
from app.db.base import Base
from app.services.shore_pass_reminders import run_shore_pass_reminders

from app.api.v1 import routes_auth, routes_contact, routes_files, routes_users, registration, routes_crew, routes_pubs, routes_hotels, routes_restaurants, routes_incidents, routes_ports, routes_drivers, routes_early_access, routes_chat, routes_superadmin, routes_reviews, routes_sightseeing, routes_notifications, routes_sos, routes_pricing_controls, routes_facilities, routes_chat_moderation

from app.api.v1.routes_vendor import router as vendor_router
from app.api.v1.routes_rfqs import router as rfq_router
from app.api.v1 import routes_quotes 
from app.api.v1 import routes_orders 
from app.api.v1 import routes_vessels
from app.api.v1 import routes_trips
from app.api.v1 import routes_agents
from app.api.v1 import routes_aggregators
from app.api.v1 import routes_bookings
from app.api.v1 import routes_itinerary
from app.api.v1 import routes_expenses
from app.api.v1 import routes_payments

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "Bearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    # Apply security globally to all endpoints (optional, but good for docs)
    openapi_schema["security"] = [{"Bearer": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app = FastAPI(
    title="OneMarinex API",
    description="""
OneMarinex Backend API providing digitized port services, crew management, 
and sustainability tracking. Connects mariners, port agents, and aggregators.

### Core Features:
* **Authentication**: JWT-based security for all roles.
* **Crew Services**: Shore pass management and booking.
* **Port Operations**: Real-time monitoring and compliance.
* **Stakeholder Portal**: Specialized access for Agents and Aggregators.
""",
    version="1.0.0",
    contact={
        "name": "OneMarinex Support",
        "email": "support@onemarinex.io",
    },
    swagger_ui_parameters={"defaultModelsExpandDepth": -1}
)

app.openapi = custom_openapi

# --- CORS config ---
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "https://heyports-56we8.ondigitalocean.app",  # Production frontend
    "https://www.heyports-56we8.ondigitalocean.app",
    "https://heyports-dev-5285u.ondigitalocean.app",
    "https://heyports.com",
    "https://www.heyports.com",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://[a-z0-9-]+\.ondigitalocean\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connection logging middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class WebSocketLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/v1/chat/ws"):
            logger = logging.getLogger("websocket_middleware")
            logger.info(f"🟢 [MIDDLEWARE] WebSocket request to {request.url.path}?{request.url.query}")
        return await call_next(request)

app.add_middleware(WebSocketLoggingMiddleware)

scheduler = BackgroundScheduler()

# --- Startup event: ensure tables exist ---
@app.on_event("startup")
def on_startup():
    # Base is already linked to all models via app/db/base.py imports
    Base.metadata.create_all(bind=engine)
    ensure_legacy_schema_columns()
    ensure_expense_bill_columns()
    ensure_chat_message_columns()
    ensure_magic_link_hardening_schema()
    ensure_port_time_and_sos_context_schema()
    ensure_vendor_commission_schema()
    ensure_agent_dashboard_schema()
    ensure_placeholder_helplines_removed()
    ensure_alembic_baseline()
    _log_whatsapp_config()
    _log_chat_moderation_config()
    scheduler.add_job(run_shore_pass_reminders, "interval", minutes=5, id="shore_pass_reminders", replace_existing=True)
    scheduler.start()


def _log_whatsapp_config() -> None:
    """State the WhatsApp config at boot, without printing any secret.

    A deploy whose env vars never made it across is otherwise indistinguishable
    from a working one until someone notices, days later, that no customer got
    a message. This one line makes it obvious in the logs on every boot.
    """
    logging.getLogger("app.startup").info(
        "WhatsApp config: enabled=%s access_token_set=%s phone_number_id_set=%s "
        "api_version=%s default_country_code=%s public_base_url=%s",
        settings.WHATSAPP_ENABLED,
        bool(settings.WHATSAPP_ACCESS_TOKEN),
        bool(settings.WHATSAPP_PHONE_NUMBER_ID),
        settings.WHATSAPP_API_VERSION,
        settings.WHATSAPP_DEFAULT_COUNTRY_CODE,
        settings.APP_PUBLIC_BASE_URL,
    )
    if not settings.WHATSAPP_ENABLED:
        logging.getLogger("app.startup").warning(
            "WhatsApp is DISABLED — no template messages will be sent from this instance."
        )
    elif not (settings.WHATSAPP_ACCESS_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID):
        logging.getLogger("app.startup").warning(
            "WhatsApp is enabled but credentials are missing — every send will be skipped."
        )


def _log_chat_moderation_config() -> None:
    """State chat moderation config at boot without printing secrets."""
    from app.services.moderation_ai import moderation_enabled

    logging.getLogger("app.startup").info(
        "Chat moderation config: ai_enabled=%s model=%s timeout=%s fail_closed=%s",
        moderation_enabled(),
        os.getenv("CHAT_MODERATION_MODEL", "claude-opus-5"),
        os.getenv("CHAT_MODERATION_TIMEOUT", "8.0"),
        os.getenv("CHAT_MODERATION_FAIL_CLOSED", "true"),
    )
    if not moderation_enabled():
        logging.getLogger("app.startup").warning(
            "ANTHROPIC_API_KEY unset — AI moderation disabled, Level 0+1 checks only."
        )


@app.on_event("shutdown")
def on_shutdown():
    scheduler.shutdown(wait=False)


def ensure_legacy_schema_columns():
    inspector = inspect(engine)
    if "aggregator_profiles" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("aggregator_profiles")}
    if "provider_type" in columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE aggregator_profiles ADD COLUMN provider_type VARCHAR(32) DEFAULT 'aggregator' NOT NULL")
        )


def ensure_chat_message_columns():
    """Reply / edit / soft-delete columns for `chat_messages`.

    Alembic migration a8e1c2d3f4b5 defines these, but nothing runs
    `alembic upgrade head` on deploy and create_all never ALTERs an existing
    table — so without this the chat endpoints would 500 with UndefinedColumn.

    Everything here is idempotent and additive, and the migration itself is
    guarded the same way, so running Alembic before or after this is safe.
    Failures are logged rather than raised: a patch problem must not stop the
    whole app from booting.
    """
    log = logging.getLogger("app.startup")
    try:
        inspector = inspect(engine)
        if "chat_messages" not in inspector.get_table_names():
            return  # fresh deploy: create_all built it with all columns

        existing = {c["name"] for c in inspector.get_columns("chat_messages")}
        additions = {
            "reply_to_id": "INTEGER",
            "edited_at": "TIMESTAMP WITH TIME ZONE",
            "deleted_at": "TIMESTAMP WITH TIME ZONE",
        }
        missing = {n: ddl for n, ddl in additions.items() if n not in existing}

        index_names = {i["name"] for i in inspector.get_indexes("chat_messages")}
        fk_names = {f.get("name") for f in inspector.get_foreign_keys("chat_messages")}
        need_index = "ix_chat_messages_reply_to_id" not in index_names
        need_fk = "fk_chat_messages_reply_to_id" not in fk_names

        if not missing and not need_index and not need_fk:
            return

        with engine.begin() as connection:
            for name, ddl in missing.items():
                connection.execute(
                    text(f"ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS {name} {ddl}")
                )
            if need_index:
                connection.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_chat_messages_reply_to_id "
                        "ON chat_messages (reply_to_id)"
                    )
                )
            if need_fk:
                # Postgres has no ADD CONSTRAINT IF NOT EXISTS; the name check
                # above plus this guard keeps a concurrent boot from erroring.
                connection.execute(
                    text(
                        "DO $$ BEGIN "
                        "ALTER TABLE chat_messages ADD CONSTRAINT fk_chat_messages_reply_to_id "
                        "FOREIGN KEY (reply_to_id) REFERENCES chat_messages (id) ON DELETE SET NULL; "
                        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
                    )
                )
        log.info(
            "chat_messages patched (columns=%s index=%s fk=%s)",
            sorted(missing), need_index, need_fk,
        )
    except Exception:
        log.exception("ensure_chat_message_columns failed — chat features may be degraded")


def ensure_expense_bill_columns():
    """`expense_bills` shipped before trip-linking / tax-split / bill-number.
    create_all never ALTERs an existing table, so add the new columns here
    (idempotent). Plain columns (no FK constraint) — ownership is validated in
    the API layer."""
    inspector = inspect(engine)
    if "expense_bills" not in inspector.get_table_names():
        return  # brand-new deploy: create_all already built it with all columns
    existing = {c["name"] for c in inspector.get_columns("expense_bills")}
    additions = {
        "amount_pre_tax": "NUMERIC(10,2)",
        "amount_post_tax": "NUMERIC(10,2)",
        "bill_number": "VARCHAR(128)",
        "shore_pass_id": "INTEGER",
        "cab_booking_id": "INTEGER",
    }
    missing = {name: ddl for name, ddl in additions.items() if name not in existing}
    if not missing:
        return
    with engine.begin() as connection:
        for name, ddl in missing.items():
            connection.execute(text(f"ALTER TABLE expense_bills ADD COLUMN IF NOT EXISTS {name} {ddl}"))


def ensure_magic_link_hardening_schema():
    """Apply the additive magic-link hardening schema on deployments that do
    not run Alembic before boot.

    The matching Alembic revisions remain the canonical migration path. These
    guarded statements make an existing DigitalOcean database safe before the
    ORM queries the new OTP fields, regardless of whether migration or app
    startup happens first.
    """
    log = logging.getLogger("app.startup")
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        link_table = "driver_magic_links"
        event_table = "driver_magic_link_reach_events"
        constraint_name = "uq_driver_magic_link_reach_event_stop"

        link_additions = {}
        if link_table in table_names:
            existing_columns = {
                column["name"] for column in inspector.get_columns(link_table)
            }
            additions = {
                "otp_verified_at": "TIMESTAMP WITH TIME ZONE",
                "otp_failed_attempts": "INTEGER DEFAULT 0 NOT NULL",
                "otp_last_attempt_at": "TIMESTAMP WITH TIME ZONE",
                "otp_locked_until": "TIMESTAMP WITH TIME ZONE",
            }
            link_additions = {
                name: ddl
                for name, ddl in additions.items()
                if name not in existing_columns
            }

        need_event_constraint = False
        if event_table in table_names:
            constraint_names = {
                constraint.get("name")
                for constraint in inspector.get_unique_constraints(event_table)
            }
            need_event_constraint = constraint_name not in constraint_names

        if not link_additions and not need_event_constraint:
            return

        with engine.begin() as connection:
            for name, ddl in link_additions.items():
                connection.execute(
                    text(
                        f"ALTER TABLE {link_table} "
                        f"ADD COLUMN IF NOT EXISTS {name} {ddl}"
                    )
                )

            if need_event_constraint:
                connection.execute(
                    text(
                        f"""
                        DELETE FROM {event_table}
                        WHERE id IN (
                            SELECT id
                            FROM (
                                SELECT
                                    id,
                                    ROW_NUMBER() OVER (
                                        PARTITION BY magic_link_id, stop_id
                                        ORDER BY reached_at DESC, id DESC
                                    ) AS duplicate_rank
                                FROM {event_table}
                            ) ranked_events
                            WHERE duplicate_rank > 1
                        )
                        """
                    )
                )
                connection.execute(
                    text(
                        f"DO $$ BEGIN "
                        f"ALTER TABLE {event_table} ADD CONSTRAINT {constraint_name} "
                        "UNIQUE (magic_link_id, stop_id); "
                        "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
                    )
                )

        log.info(
            "driver magic-link schema patched (columns=%s unique_stop=%s)",
            sorted(link_additions),
            need_event_constraint,
        )
    except Exception:
        log.exception(
            "ensure_magic_link_hardening_schema failed — driver magic-link actions may be degraded"
        )


def ensure_port_time_and_sos_context_schema():
    """Additive fallback for server-authoritative port time and trip-bound SOS.

    Alembic remains canonical. This guard prevents an App Platform instance
    that starts before the migration job from querying columns that do not yet
    exist.
    """
    log = logging.getLogger("app.startup")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        statements = []

        if "port_rules" in tables:
            port_columns = {column["name"] for column in inspector.get_columns("port_rules")}
            if "timezone" not in port_columns:
                statements.append(
                    "ALTER TABLE port_rules ADD COLUMN IF NOT EXISTS timezone VARCHAR(64)"
                )
            statements.append(
                """
                UPDATE port_rules
                   SET timezone = CASE
                       WHEN lower(port_name) LIKE '%dubai%' THEN 'Asia/Dubai'
                       ELSE 'Asia/Kolkata'
                   END
                 WHERE timezone IS NULL OR btrim(timezone) = ''
                """
            )

        if "crew_sos_requests" in tables:
            sos_columns = {
                column["name"] for column in inspector.get_columns("crew_sos_requests")
            }
            additions = {
                "cab_booking_id": "INTEGER",
                "trip_id": "VARCHAR(64)",
                "crew_email": "VARCHAR(255)",
                "sos_email": "VARCHAR(255)",
            }
            for name, ddl in additions.items():
                if name not in sos_columns:
                    statements.append(
                        f"ALTER TABLE crew_sos_requests ADD COLUMN IF NOT EXISTS {name} {ddl}"
                    )

            has_booking_fk = any(
                foreign_key.get("constrained_columns") == ["cab_booking_id"]
                and foreign_key.get("referred_table") == "cab_bookings"
                for foreign_key in inspector.get_foreign_keys("crew_sos_requests")
            )

            statements.extend([
                "CREATE INDEX IF NOT EXISTS ix_crew_sos_requests_cab_booking_id ON crew_sos_requests (cab_booking_id)",
                "CREATE INDEX IF NOT EXISTS ix_crew_sos_requests_trip_id ON crew_sos_requests (trip_id)",
            ])
            if not has_booking_fk and "cab_bookings" in tables:
                statements.append("""
                DO $$ BEGIN
                    ALTER TABLE crew_sos_requests
                    ADD CONSTRAINT fk_crew_sos_requests_cab_booking_id
                    FOREIGN KEY (cab_booking_id) REFERENCES cab_bookings(id) ON DELETE SET NULL;
                EXCEPTION WHEN duplicate_object THEN NULL; END $$;
                """)

        if not statements:
            return
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
        log.info("port timezone and trip-bound SOS schema verified")
    except Exception:
        log.exception(
            "ensure_port_time_and_sos_context_schema failed — time/SOS features may be degraded"
        )


def ensure_vendor_commission_schema():
    """Additive safety net for deployments that start before Alembic runs."""
    log = logging.getLogger("app.startup")
    try:
        inspector = inspect(engine)
        if "vendors" not in inspector.get_table_names():
            return

        columns = {column["name"] for column in inspector.get_columns("vendors")}
        statements = []
        if "commission_percentage" not in columns:
            statements.append(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS commission_percentage NUMERIC(5,2) DEFAULT 0 NOT NULL"
            )

        statements.append(
            "CREATE INDEX IF NOT EXISTS ix_vendors_port_category_commission ON vendors (port_id, category, commission_percentage)"
        )

        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
        log.info("vendor commission schema verified")
    except Exception:
        log.exception(
            "ensure_vendor_commission_schema failed — vendor ranking may be degraded"
        )



def ensure_agent_dashboard_schema():
    """Additive safety net for the agent dashboard work.

    Mirrors migrations w1c2d3e4f5g6, x1c2d3e4f5g6 and y1c2d3e4f5g6, the same way
    the guards above mirror theirs. `create_all()` covers the two new tables
    because it creates missing tables, but it never ALTERs an existing one, so
    these columns would otherwise be absent until a pre-deploy job runs — and
    every incident query selects `incidents.vessel_id`.

    Alembic remains canonical. This exists so a deploy that starts before the
    migration job cannot leave the API returning UndefinedColumn.
    """
    log = logging.getLogger("app.startup")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        statements = []

        if "incidents" in tables:
            columns = {c["name"] for c in inspector.get_columns("incidents")}
            for name, ddl in (
                ("vessel_id", "INTEGER"),
                ("category", "VARCHAR(64)"),
                ("sub_category", "VARCHAR(64)"),
                ("severity", "VARCHAR(16)"),
                ("resolved_at", "TIMESTAMP"),
                ("cancelled_at", "TIMESTAMP"),
            ):
                if name not in columns:
                    statements.append(
                        f"ALTER TABLE incidents ADD COLUMN IF NOT EXISTS {name} {ddl}"
                    )
            statements.append(
                "CREATE INDEX IF NOT EXISTS ix_incidents_vessel_id ON incidents (vessel_id)"
            )
            # Same constraint the migration creates. Named so the two agree and
            # whichever runs second is a no-op.
            fks = {fk.get("name") for fk in inspector.get_foreign_keys("incidents")}
            if "fk_incidents_vessel_id" not in fks and "vessels" in tables:
                statements.append(
                    "ALTER TABLE incidents ADD CONSTRAINT fk_incidents_vessel_id "
                    "FOREIGN KEY (vessel_id) REFERENCES vessels (id) ON DELETE SET NULL"
                )
            statements.append(
                "CREATE INDEX IF NOT EXISTS ix_incidents_category ON incidents (category)"
            )

        if "agent_profiles" in tables:
            columns = {c["name"] for c in inspector.get_columns("agent_profiles")}
            if "agency_logo_url" not in columns:
                statements.append(
                    "ALTER TABLE agent_profiles ADD COLUMN IF NOT EXISTS agency_logo_url VARCHAR(512)"
                )

        if "vessels" in tables:
            columns = {c["name"] for c in inspector.get_columns("vessels")}
            if "shore_pass_valid_upto" not in columns:
                statements.append(
                    "ALTER TABLE vessels ADD COLUMN IF NOT EXISTS shore_pass_valid_upto TIMESTAMP WITH TIME ZONE"
                )

        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

        # ALTER TYPE ... ADD VALUE cannot run inside a transaction block before
        # Postgres 12, so it goes on its own autocommit connection rather than
        # sharing the block above.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(
                text("ALTER TYPE incidentstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")
            )

        log.info("agent dashboard schema verified (%s statement(s))", len(statements))
    except Exception:
        log.exception(
            "ensure_agent_dashboard_schema failed — incident, vessel and agent "
            "profile endpoints may return UndefinedColumn until migrations run"
        )


def ensure_placeholder_helplines_removed():
    """Remove retired demo helplines when no pre-deploy job is configured.

    Alembic remains canonical. This idempotent startup guard mirrors the other
    deployment fallbacks in this module because the checked-in Procfile starts
    only the web process and does not run Alembic itself.
    """
    log = logging.getLogger("app.startup")
    placeholders = {
        "placeholder_one": "+91 1800-HEYPORTS",
        "placeholder_two": "+91 1800 425 1234",
    }
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        targets = []
        for table_name in ("cab_bookings", "port_rules"):
            if table_name not in tables:
                continue
            columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            if "helpline_number" in columns:
                targets.append(table_name)

        cleared = 0
        with engine.begin() as connection:
            for table_name in targets:
                result = connection.execute(
                    text(
                        f"UPDATE {table_name} SET helpline_number = NULL "
                        "WHERE helpline_number IN (:placeholder_one, :placeholder_two)"
                    ),
                    placeholders,
                )
                cleared += max(result.rowcount or 0, 0)
        log.info("retired helpline cleanup verified (cleared=%s)", cleared)
    except Exception:
        log.exception(
            "ensure_placeholder_helplines_removed failed — retired demo helplines may remain visible"
        )

def ensure_alembic_baseline():
    """Make Alembic usable against a database that was never stamped.

    Every deployment so far built its schema with `create_all()` and never ran
    Alembic, so there is no `alembic_version` row. Alembic cannot fix that
    itself: this project's history is not replayable from base — the earliest
    revision alters `rfqs` / `rfq_quotes`, tables from a retired product, and
    dies with UndefinedTable on an empty database.

    Stamping records that the schema `create_all()` produced is equivalent to
    head, which is what lets future revisions apply as ordinary deltas. It runs
    no migration DDL, so it cannot fail partway.

    A pre-deploy job (`python -m app.db.migrate`) is the intended place for
    applying deltas. This is only the safety net that guarantees the baseline
    exists even if that job is never configured.
    """
    log = logging.getLogger("app.startup")
    try:
        from app.db.migrate import baseline_if_unstamped

        if baseline_if_unstamped():
            log.info("alembic baseline stamped at head")
    except Exception:
        log.exception(
            "ensure_alembic_baseline failed — Alembic migrations will not apply "
            "until this database is stamped"
        )


# --- Routes ---
app.include_router(routes_auth.router,    prefix="/api/v1/auth",    tags=["authentication"])
app.include_router(routes_contact.router, prefix="/api/v1/contact", tags=["contact"])
app.include_router(routes_early_access.router, prefix="/api/v1/early-access", tags=["early-access"])
app.include_router(routes_files.router,   prefix="/api/v1/files",   tags=["files"])
app.include_router(routes_users.router,   prefix="/api/v1/users",   tags=["users"])
app.include_router(vendor_router,         prefix="/api/v1",         tags=["vendor"])
app.include_router(rfq_router, prefix="/api/v1", tags=["rfqs"])
app.include_router(routes_quotes.router, prefix="/api/v1", tags=["quotes"])
app.include_router(routes_orders.router,  prefix="/api/v1",         tags=["orders"])
app.include_router(registration.router,   prefix="/api/v1/registration", tags=["registration"])
app.include_router(routes_crew.router,     prefix="/api/v1/crew",         tags=["crew"])
app.include_router(routes_pubs.router,     prefix="/api/v1/pubs",         tags=["pubs"])
app.include_router(routes_hotels.router,   prefix="/api/v1/hotels",       tags=["hotels"])
app.include_router(routes_sightseeing.router, prefix="/api/v1/sightseeing", tags=["sightseeing"])
app.include_router(routes_restaurants.router, prefix="/api/v1/restaurants",   tags=["restaurants"])
app.include_router(routes_vessels.router,     prefix="/api/v1/vessels",       tags=["vessels"])
app.include_router(routes_trips.router,       prefix="/api/v1/trips",         tags=["trips"])
app.include_router(routes_incidents.router, prefix="/api/v1/incidents", tags=["incidents"])
app.include_router(routes_agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(routes_aggregators.router, prefix="/api/v1/aggregators", tags=["aggregators"])
app.include_router(routes_bookings.router, prefix="/api/v1/bookings", tags=["bookings"])
app.include_router(routes_ports.router, prefix="/api/v1/ports", tags=["ports"])
app.include_router(routes_drivers.router, prefix="/api/v1/drivers", tags=["drivers"])
app.include_router(routes_chat.router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(routes_superadmin.router, prefix="/api/v1/superadmin", tags=["superadmin"])
app.include_router(routes_pricing_controls.router, prefix="/api/v1/superadmin", tags=["pricing-controls"])
app.include_router(routes_chat_moderation.router, prefix="/api/v1/superadmin", tags=["chat-moderation"])
app.include_router(routes_reviews.router, prefix="/api/v1/reviews", tags=["reviews"])
app.include_router(routes_notifications.router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(routes_sos.router, prefix="/api/v1/sos", tags=["sos"])
app.include_router(routes_itinerary.router, prefix="/api/v1/itinerary", tags=["itinerary"])
app.include_router(routes_facilities.router, prefix="/api/v1/facilities", tags=["facilities"])
app.include_router(routes_expenses.router, prefix="/api/v1/crew/expense-bills", tags=["expenses"])
app.include_router(routes_payments.router, prefix="/api/v1/crew/payments", tags=["payments"])


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
