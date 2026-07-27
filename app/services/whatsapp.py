"""WhatsApp Business Cloud API (Meta Graph API) template message sending.

Fire-and-forget by design: every public function here catches its own
exceptions and returns True/False instead of raising, so a WhatsApp/network
failure never blocks the booking/driver/review flow that triggered it.
"""
import logging
import re
from typing import List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"


def normalize_whatsapp_number(raw: Optional[str]) -> Optional[str]:
    """Return digits-only, country-code-prefixed phone (no leading '+'), or
    None if unusable. Assumes India (settings.WHATSAPP_DEFAULT_COUNTRY_CODE)
    for bare 10-digit numbers, since this app is India-only today."""
    if not raw:
        return None
    had_plus = raw.strip().startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if not had_plus:
        if digits.startswith("0"):
            digits = settings.WHATSAPP_DEFAULT_COUNTRY_CODE + digits.lstrip("0")
        elif len(digits) == 10:
            digits = settings.WHATSAPP_DEFAULT_COUNTRY_CODE + digits
    if not (10 <= len(digits) <= 15):
        return None
    return digits



# Layer 1 — shape detection. Matches any KEY=VALUE assignment whose key
# contains a sensitive word anywhere in it, so SECRET_KEY=, WHATSAPP_ACCESS_TOKEN=
# and DB_PASSWORD= are all caught, not just bare SECRET=.
_CREDENTIAL_PATTERN = re.compile(
    r"[A-Z0-9_]*"
    r"(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|PRIVATE_?KEY|CREDENTIAL|DATABASE_URL|AUTH)"
    r"[A-Z0-9_]*\s*=",
    re.IGNORECASE,
)

# Layer 2 — value detection. Shape matching can always be evaded by a
# differently-formatted leak, so also refuse to transmit anything containing
# the literal value of a real secret. Short values are ignored to avoid
# matching ordinary text.
_MIN_SECRET_LEN = 8


def _known_secret_values() -> List[str]:
    values = [
        getattr(settings, "WHATSAPP_ACCESS_TOKEN", "") or "",
        getattr(settings, "SECRET_KEY", "") or "",
        getattr(settings, "DATABASE_URL", "") or "",
    ]
    return [v for v in values if isinstance(v, str) and len(v) >= _MIN_SECRET_LEN]


class UnsafeTemplateParamError(Exception):
    pass


def _sanitize_param(value) -> str:
    """Meta rejects template params with newlines or 4+ consecutive spaces.

    Also refuses outright to pass through anything that looks like — or
    literally contains — a credential, so a bug or mistaken call upstream
    can never put a secret on the wire to an external phone number."""
    text = str(value if value is not None else "")
    if _CREDENTIAL_PATTERN.search(text):
        raise UnsafeTemplateParamError(
            "Refusing to send a template parameter that looks like a credential assignment"
        )
    for secret in _known_secret_values():
        if secret in text:
            raise UnsafeTemplateParamError(
                "Refusing to send a template parameter containing a known secret value"
            )
    return re.sub(r"\s+", " ", text).strip()


def _post_template_message(
    to: str,
    template_name: str,
    body_params: List[str],
    button_params: Optional[List[str]] = None,
) -> bool:
    url = f"{GRAPH_BASE}/{settings.WHATSAPP_API_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "en"},
        },
    }
    try:
        components = []
        if body_params:
            components.append({
                "type": "body",
                "parameters": [{"type": "text", "text": _sanitize_param(p)} for p in body_params],
            })

        for index, param in enumerate(button_params or []):
            components.append({
                "type": "button",
                "sub_type": "url",
                "index": str(index),
                "parameters": [{"type": "text", "text": _sanitize_param(param)}],
            })
        if components:
            payload["template"]["components"] = components
    except UnsafeTemplateParamError:
        logger.error(
            "WhatsApp send BLOCKED — a parameter for template=%s looked like a credential assignment. "
            "Not sending. body_params=%s button_params=%s",
            template_name, body_params, button_params,
        )
        return False
    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10.0,
        )
        if response.status_code >= 400:
            logger.warning(
                "WhatsApp send failed template=%s status=%s body=%s",
                template_name, response.status_code, response.text,
            )
            return False
        return True
    except Exception:
        logger.exception("WhatsApp send raised template=%s", template_name)
        return False


def send_whatsapp_template(
    raw_phone: Optional[str],
    template_name: str,
    body_params: List[str],
    button_params: Optional[List[str]] = None,
) -> bool:
    if not settings.WHATSAPP_ENABLED:
        return False
    if not settings.WHATSAPP_ACCESS_TOKEN or not settings.WHATSAPP_PHONE_NUMBER_ID:
        logger.warning("WhatsApp not configured — skipping template=%s", template_name)
        return False
    to = normalize_whatsapp_number(raw_phone)
    if not to:
        logger.info("WhatsApp skipped, no usable phone number for template=%s", template_name)
        return False
    return _post_template_message(to, template_name, body_params, button_params)


# Translates booking_service.STATUS_LABELS' internal/operational wording
# ("Pending Provider Response") into customer-facing phrasing for WhatsApp.
# Deliberately kept separate from STATUS_LABELS itself — that dict also
# drives admin dashboards, where the more precise/technical wording is
# actually what ops staff want to see.
_FRIENDLY_STATUS = {
    "Pending Provider Response": "Trip Requested",
    "Provider Accepted": "Provider Confirmed",
    "Provider Rejected": "Finding You Another Ride",
    "Driver Assigned": "Driver Assigned",
    "Driver Accepted": "Driver Confirmed",
    "On Trip": "Trip In Progress",
    "Completed": "Trip Completed",
    "Cancelled": "Trip Cancelled",
}


def _status(value) -> str:
    return _FRIENDLY_STATUS.get(value, value)


# --- One wrapper per approved template. Param order must match the exact
# order the template was approved with in Meta Business Manager. ---

def notify_crew_package_trip_state(phone, status, trip_id, trip_type, pickup, passengers, duration) -> bool:
    return send_whatsapp_template(
        phone, "crew_package_trip_state",
        [_status(status), trip_id, trip_type, pickup, passengers, duration],
    )


def notify_crew_coordinated_transfer_trip_state(phone, status, trip_id, trip_type, pickup, drop, passengers) -> bool:
    return send_whatsapp_template(
        phone, "crew_coordinated_transfer_trip_state",
        [_status(status), trip_id, trip_type, pickup, drop, passengers],
    )


def notify_aggregator_trip_request(phone, trip_id, trip_type, pickup, passengers, duration) -> bool:
    return send_whatsapp_template(
        phone, "aggregator_trip_request",
        [trip_id, trip_type, pickup, passengers, duration],
    )


def notify_aggregator_coordinated_transfer_trip_request(phone, trip_id, trip_type, pickup, drop, passengers) -> bool:
    # Approved template name is spelled "transer" (not "transfer") — verbatim per Meta Business Manager.
    return send_whatsapp_template(
        phone, "aggregator_coordinated_transer_trip_request",
        [trip_id, trip_type, pickup, drop, passengers],
    )


def notify_driver_alloted(phone, trip_id, driver_name, vehicle, pickup_address, contact) -> bool:
    # 4th field relabeled "Pickup" (was "Pickup Time") in Meta Business
    # Manager — now sends the pickup address/location, not the scheduled time.
    return send_whatsapp_template(
        phone, "driver_alloted_state",
        [trip_id, driver_name, vehicle, pickup_address, contact],
    )


def notify_driver_arrival(phone, trip_id) -> bool:
    return send_whatsapp_template(phone, "driver_arrival", [trip_id])


def notify_facility_reached(phone, trip_id, passengers, facility) -> bool:
    return send_whatsapp_template(phone, "facility_reached", [trip_id, passengers, facility])


def notify_trip_rejection(phone) -> bool:
    return send_whatsapp_template(phone, "trip_rejection", [])


def notify_submit_review(phone) -> bool:
    # Built here, not accepted from the caller — this template's only
    # parameter is a URL, and there's no legitimate reason for any caller to
    # supply that string themselves rather than us deriving it from the one
    # trusted setting that's meant to be public anyway.
    review_url = f"{settings.APP_PUBLIC_BASE_URL}/bookings"
    return send_whatsapp_template(phone, "submit_review", [review_url])


def notify_sos_crew_in_danger(phone) -> bool:
    return send_whatsapp_template(phone, "sos_message_to_crew_in_danger", [])


def notify_sos_crew_and_admin(phone, trip_id, crew_name, vessel, location) -> bool:
    return send_whatsapp_template(
        phone, "sos_message_to_crew_and_admin",
        [trip_id, crew_name, vessel, location],
    )


def notify_sos_aggregator(phone, trip_id, location, time_str, lat=None, lng=None) -> bool:
    # The approved template has a "Navigate to location" URL button (index 0)
    # that Meta rejects the send without a dynamic parameter for — confirmed
    # via a live test send: "(#131008) Button at index 0 of type Url requires
    # a parameter". The parameter is the button's dynamic URL suffix, verified
    # against the real API as a bare "lat,lng" pair (no space).
    button_value = f"{lat},{lng}" if lat is not None and lng is not None else "unavailable"
    return send_whatsapp_template(
        phone, "sos_message_to_aggregator",
        [trip_id, location, time_str],
        button_params=[button_value],
    )


def notify_return_reminder(phone) -> bool:
    return send_whatsapp_template(phone, "return_reminder", [])


def notify_critical_return_reminder(phone) -> bool:
    return send_whatsapp_template(phone, "critical_return_reminder", [])
