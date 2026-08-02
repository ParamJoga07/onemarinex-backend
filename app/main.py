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
