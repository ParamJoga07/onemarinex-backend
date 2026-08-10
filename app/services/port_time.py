"""Server-authoritative port clock and opening-hours helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


logger = logging.getLogger(__name__)

HHMM_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?$")
WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# All currently supported ports are in India except Dubai. PortRule.timezone is
# configurable for future ports; this fallback keeps existing rows correct
# before an operator explicitly saves a timezone.
DEFAULT_PORT_TIMEZONE = "Asia/Kolkata"


def minutes_from_hhmm(value: str) -> int:
    match = HHMM_PATTERN.fullmatch((value or "").strip())
    if not match:
        raise ValueError("Time must use HH:MM format")
    return int(match.group(1)) * 60 + int(match.group(2))


def normalize_working_days(raw) -> Optional[List[str]]:
    """Working days may be stored as a JSON list, JSON string, or CSV."""
    if not raw:
        return None
    values = raw
    if isinstance(values, str):
        text = values.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            values = parsed if isinstance(parsed, list) else text.split(",")
        except (ValueError, TypeError):
            values = text.split(",")
    if not isinstance(values, list):
        return None
    days = {str(value).strip()[:3].title() for value in values if str(value).strip()}
    return sorted(days) or None


def inferred_port_timezone(port_value: Optional[str]) -> str:
    normalized = (port_value or "").strip().lower()
    if "dubai" in normalized:
        return "Asia/Dubai"
    return DEFAULT_PORT_TIMEZONE


def resolve_port_timezone(
    port_value: Optional[str],
    configured_timezone: Optional[str] = None,
) -> tuple[str, ZoneInfo]:
    timezone_name = (configured_timezone or "").strip() or inferred_port_timezone(port_value)
    try:
        return timezone_name, ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        fallback = inferred_port_timezone(port_value)
        logger.warning(
            "Invalid timezone %r configured for port %r; using %s",
            timezone_name,
            port_value,
            fallback,
        )
        return fallback, ZoneInfo(fallback)


def validate_timezone_name(value: str) -> str:
    timezone_name = (value or "").strip()
    if not timezone_name:
        raise ValueError("Timezone is required")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Timezone must be a valid IANA timezone") from exc
    return timezone_name


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_port_local(value: datetime, port_zone: ZoneInfo) -> datetime:
    """Interpret naive booking input as the configured port's wall clock."""
    if value.tzinfo is None:
        return value.replace(tzinfo=port_zone)
    return value.astimezone(port_zone)


def port_clock_snapshot(
    port_value: Optional[str],
    configured_timezone: Optional[str] = None,
    now_utc: Optional[datetime] = None,
) -> dict:
    timezone_name, port_zone = resolve_port_timezone(port_value, configured_timezone)
    authoritative_utc = now_utc or utc_now()
    if authoritative_utc.tzinfo is None:
        authoritative_utc = authoritative_utc.replace(tzinfo=timezone.utc)
    authoritative_utc = authoritative_utc.astimezone(timezone.utc)
    port_now = authoritative_utc.astimezone(port_zone)
    return {
        "timezone": timezone_name,
        "zone": port_zone,
        "server_time": authoritative_utc,
        "port_now": port_now,
        "port_date": port_now.strftime("%Y-%m-%d"),
        "port_time": port_now.strftime("%H:%M"),
        "port_day": WEEKDAY_ABBR[port_now.weekday()],
    }


def port_closed_reason(
    pickup_at: datetime,
    opening_time: Optional[str],
    closing_time: Optional[str],
    working_days,
) -> Optional[str]:
    """Return the configured reason a pickup cannot occur, if any."""
    days = normalize_working_days(working_days)
    if days and WEEKDAY_ABBR[pickup_at.weekday()] not in days:
        return "The port is closed on %s." % pickup_at.strftime("%A")

    try:
        opening = minutes_from_hhmm(opening_time) if opening_time else None
        closing = minutes_from_hhmm(closing_time) if closing_time else None
    except ValueError:
        logger.error(
            "Port timing is not HH:MM (opening=%r closing=%r); blocking timed actions",
            opening_time,
            closing_time,
        )
        return "Port timing is temporarily unavailable. Please contact port support."

    if opening is None and closing is None:
        return None

    pickup_minutes = pickup_at.hour * 60 + pickup_at.minute
    if opening is not None and closing is not None:
        if closing <= opening:
            closing += 24 * 60
            if pickup_minutes < opening:
                pickup_minutes += 24 * 60
        if pickup_minutes < opening:
            return "The port opens at %s. Choose a pickup time at or after opening." % opening_time[:5]
        if pickup_minutes >= closing:
            return "The port closed at %s. Choose a pickup time within port hours." % closing_time[:5]
        return None

    if opening is not None and pickup_minutes < opening:
        return "The port opens at %s. Choose a pickup time at or after opening." % opening_time[:5]
    if closing is not None and pickup_minutes >= closing:
        return "The port closed at %s. Choose a pickup time within port hours." % closing_time[:5]
    return None


def port_closing_buffer_reason(
    current_port_time: datetime,
    opening_time: Optional[str],
    closing_time: Optional[str],
    minimum_remaining_minutes: int,
) -> Optional[str]:
    """Block an immediate action during the final minutes before closing.

    ``current_port_time`` must come from :func:`port_clock_snapshot`, not from
    a client-supplied timestamp. Overnight schedules are projected onto a
    single minute timeline so a 22:00-02:00 port has the correct cutoff on
    both sides of midnight.
    """
    if not closing_time or minimum_remaining_minutes <= 0:
        return None

    try:
        closing = minutes_from_hhmm(closing_time)
        opening = minutes_from_hhmm(opening_time) if opening_time else None
    except ValueError:
        logger.error(
            "Port timing is not HH:MM (opening=%r closing=%r); blocking timed actions",
            opening_time,
            closing_time,
        )
        return "Port timing is temporarily unavailable. Please contact port support."

    current = current_port_time.hour * 60 + current_port_time.minute
    if opening is not None and closing <= opening and current >= opening:
        closing += 24 * 60

    remaining = closing - current
    if remaining <= minimum_remaining_minutes:
        hours = minimum_remaining_minutes / 60
        hours_label = str(int(hours)) if hours.is_integer() else f"{hours:g}"
        return (
            f"Go Explore is unavailable during the final {hours_label} hours "
            f"before the port closes at {closing_time[:5]}."
        )
    return None


def port_day_bounds(
    port_value: Optional[str],
    configured_timezone: Optional[str] = None,
    on_date: Optional[str] = None,
) -> tuple[datetime, datetime, str]:
    """The UTC instants bracketing one calendar day *at the port*.

    "Today" was previously `datetime.utcnow().replace(hour=0, ...)`, which for
    an Indian port runs 05:30 IST to 05:30 IST. The agent's "resolved today"
    tile therefore counted work from yesterday afternoon and stayed empty until
    half past five each morning.

    `on_date` is a YYYY-MM-DD string as the agent typed it — a date on *their*
    calendar, not UTC's. Returns (start_utc, end_utc, resolved_date_string).
    """
    _, zone = resolve_port_timezone(port_value, configured_timezone)

    if on_date:
        try:
            local_midnight = datetime.strptime(on_date, "%Y-%m-%d").replace(tzinfo=zone)
        except ValueError:
            raise ValueError("Date must use YYYY-MM-DD format")
    else:
        local_midnight = datetime.now(zone).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    start = local_midnight.astimezone(timezone.utc)
    end = (local_midnight + timedelta(days=1)).astimezone(timezone.utc)
    return start, end, local_midnight.strftime("%Y-%m-%d")


def agent_port_day(db, current_user, on_date: Optional[str] = None):
    """`port_day_bounds` for the port an agent is assigned to."""
    from app.db.models.port_rule import PortRule

    port = None
    profile = getattr(current_user, "agent_profile", None)
    if profile is not None:
        port = getattr(profile, "assigned_port", None)

    configured = None
    if port:
        row = db.query(PortRule.timezone).filter(PortRule.port_name == port).first()
        configured = row[0] if row else None

    return port_day_bounds(port, configured, on_date)
