"""Shared, server-owned context for incident, SOS, and report detail views."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.db.models.cab_booking import CabBooking
from app.db.models.driver_magic_link import DriverMagicLink
from app.db.models.vessel import Vessel
from app.services.magic_link_service import serialize_magic_link_public_payload


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


def booking_context(db: Session, booking: Optional[CabBooking]):
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

    reached = [item for item in stops if item["reached"]]
    reached.sort(key=lambda item: str(item.get("reached_at") or ""))
    next_stop = next((item for item in stops if not item["reached"]), None)
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
