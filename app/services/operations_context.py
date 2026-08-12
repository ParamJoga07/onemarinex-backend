"""Shared, server-owned context for incident, SOS, and report detail views."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models.cab_booking import CabBooking
from app.db.models.driver_magic_link import DriverMagicLink
from app.db.models.vessel import Vessel
from app.services.magic_link_service import serialize_magic_link_public_payload

# Sorts before every real timestamp, for stops recorded without one.
_EARLIEST = datetime.min.replace(tzinfo=timezone.utc)

_ENDED_STATUSES = {"completed", "cancelled"}


def _as_instant(value) -> Optional[datetime]:
    """A comparable UTC instant from a datetime or ISO string, else None.

    Timestamps reach here from two places — database columns, which may be
    naive — and magic-link JSON, which is a string. Naive values are read as
    UTC so the two can be compared at all.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _reached_instant(stop) -> Optional[datetime]:
    return _as_instant(stop.get("reached_at"))


def _trip_had_ended(booking: CabBooking, cutoff: Optional[datetime]) -> bool:
    """Was the trip already over at `cutoff` (or now, when none is given)?"""
    ended_at = _as_instant(booking.trip_completed_at or booking.completed_at)
    if ended_at is not None:
        return cutoff is None or ended_at <= cutoff
    status = getattr(booking.status, "value", booking.status)
    # Without a completion timestamp the status is all there is, and it
    # describes the trip now — so it can only settle the question when the
    # report is also about now.
    return cutoff is None and str(status or "").lower() in _ENDED_STATUSES


def vessel_context(vessel: Optional[Vessel], *, port_name: Optional[str] = None):
    if not vessel:
        return None
    return {
        "id": vessel.id,
        "name": vessel.name,
        "imo_number": vessel.imo_number,
        "port_name": port_name,
        "flag": vessel.flag,
        "eta": vessel.eta,
        "etd": vessel.etd,
        "berth": vessel.berth_assignment,
    }


def find_booking(db: Session, reference: Optional[str], *, booking_id: Optional[int] = None):
    if booking_id is not None:
        return db.query(CabBooking).filter(CabBooking.id == booking_id).first()
    if not reference:
        return None
    return db.query(CabBooking).filter(CabBooking.booking_id == reference).first()


def booking_context(db: Session, booking: Optional[CabBooking], *, as_of=None):
    """Trip detail for a report.

    `as_of` is the moment the report is about — when an SOS was raised, or an
    incident filed. Without it this describes the trip *now*, which is wrong on
    both counts a report cares about: an SOS raised after the first stop reads
    back as "Trip End (Port)" once the cab has since finished, and a trip that
    ended with a stop skipped still advertises that stop as where the crew were
    heading next.
    """
    if not booking:
        return None

    magic_link = (
        db.query(DriverMagicLink)
        .filter(DriverMagicLink.booking_id == booking.id)
        .order_by(DriverMagicLink.id.desc())
        .first()
    )
    stops = []
    if magic_link:
        payload = serialize_magic_link_public_payload(magic_link)
        source_stops = payload.get("itinerary") or []
        for index, stop in enumerate(source_stops):
            stops.append({
                "id": stop.get("id"),
                "name": stop.get("name"),
                "address": stop.get("address"),
                "type": stop.get("type"),
                "reached": bool(stop.get("reached")),
                "reached_at": stop.get("reached_at"),
                "position": index,
            })

    # Ordered by when each stop was actually reached, parsed rather than
    # compared as strings: mixed formats and empty values sort by accident.
    # Stops with no timestamp keep their itinerary position as the tiebreak.
    reached = [item for item in stops if item["reached"]]
    reached.sort(key=lambda item: (
        _reached_instant(item) or _EARLIEST, item["position"],
    ))

    cutoff = _as_instant(as_of)
    if cutoff is not None:
        # A stop reached after the moment in question had not been reached yet.
        reached = [
            item for item in reached
            if (_reached_instant(item) or _EARLIEST) <= cutoff
        ]

    reached_ids = {id(item) for item in reached}
    next_stop = next((item for item in stops if id(item) not in reached_ids), None)

    # Once the trip is over there is no next destination, whether or not every
    # stop was visited. Crew skip stops and go back to the ship; the skipped one
    # is not where they were heading.
    if _trip_had_ended(booking, cutoff):
        next_stop = None
    provider = booking.provider or booking.aggregator
    driver = booking.assigned_driver
    status_value = booking.status.value if hasattr(booking.status, "value") else str(booking.status)

    return {
        "id": booking.id,
        "booking_id": booking.booking_id,
        "status": status_value,
        "ride_type": booking.ride_type.value if getattr(booking.ride_type, "value", None) else booking.ride_type,
        "pickup_address": booking.pickup_address,
        "drop_address": booking.drop_address,
        "driver_name": booking.driver_name or (driver.name if driver else None),
        "driver_phone": booking.driver_phone or (driver.phone if driver else None),
        "vehicle_number": booking.driver_plate or (driver.vehicle_number if driver else None),
        "provider_name": booking.aggregator_name or (provider.company_name if provider else None),
        "last_reached_point": reached[-1] if reached else None,
        "next_destination": next_stop,
        "planned_stops": stops,
        "tracking_available": magic_link is not None,
        "created_at": booking.created_at,
        "started_at": booking.trip_started_at or booking.started_at,
        "completed_at": booking.trip_completed_at or booking.completed_at,
    }
