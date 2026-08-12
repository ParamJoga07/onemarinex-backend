from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models.booking_timeline import BookingTimeline, TimelineEventType
from app.db.models.cab_booking import CabBooking, BookingStatus


EVENT_LABELS = {
    TimelineEventType.BOOKING_CREATED: "Booking Created",
    TimelineEventType.PROVIDER_NOTIFIED: "Provider Notified",
    TimelineEventType.PROVIDER_ACCEPTED: "Provider Accepted",
    TimelineEventType.PROVIDER_REJECTED: "Provider Rejected",
    TimelineEventType.DRIVER_ASSIGNED: "Driver Assigned",
    TimelineEventType.DRIVER_ACCEPTED: "Driver Accepted",
    TimelineEventType.TRIP_STARTED: "Trip Started",
    TimelineEventType.TRIP_COMPLETED: "Trip Completed",
    TimelineEventType.TRIP_CANCELLED: "Trip Cancelled",
}

STOP_EVENT_LABELS = {
    "pickup": "Pickup Point",
    "drop": "Drop Point",
    "waypoint": "Waypoint",
    "facility": "Facility Stop",
    "custom": "Driver Added Stop",
}

EVENT_SORT_ORDER = {
    TimelineEventType.BOOKING_CREATED.value: 10,
    TimelineEventType.PROVIDER_NOTIFIED.value: 20,
    TimelineEventType.PROVIDER_ACCEPTED.value: 30,
    TimelineEventType.PROVIDER_REJECTED.value: 30,
    TimelineEventType.DRIVER_ASSIGNED.value: 40,
    TimelineEventType.DRIVER_ACCEPTED.value: 50,
    TimelineEventType.TRIP_STARTED.value: 60,
    TimelineEventType.TRIP_COMPLETED.value: 90,
    TimelineEventType.TRIP_CANCELLED.value: 90,
}


def create_timeline_event(
    db: Session,
    *,
    booking_db_id: int,
    event_type: TimelineEventType,
    actor_id: Optional[int] = None,
    actor_type: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    event_time: Optional[datetime] = None,
) -> BookingTimeline:
    entry = BookingTimeline(
        booking_id=booking_db_id,
        event_type=event_type.value,
        event_time=event_time or datetime.utcnow(),
        actor_id=actor_id,
        actor_type=actor_type,
        event_metadata=metadata,
    )
    db.add(entry)
    return entry


def get_booking_timeline(db: Session, booking_db_id: int) -> List[Dict[str, Any]]:
    entries = (
        db.query(BookingTimeline)
        .filter(BookingTimeline.booking_id == booking_db_id)
        .order_by(BookingTimeline.event_time.asc(), BookingTimeline.id.asc())
        .all()
    )
    events: List[Dict[str, Any]] = [
        {
            "id": entry.id,
            "event_type": entry.event_type,
            "event_label": EVENT_LABELS.get(TimelineEventType(entry.event_type), entry.event_type),
            "event_time": entry.event_time,
            "actor_id": entry.actor_id,
            "actor_type": entry.actor_type,
            "metadata": entry.event_metadata,
            "created_at": entry.created_at,
        }
        for entry in entries
    ]

    # Old imports and local seed fixtures predate booking_timeline. Their
    # lifecycle timestamps still belong on the timeline; otherwise a completed
    # booking opens to a completely blank screen. Only exact persisted times are
    # projected here — updated_at is intentionally not treated as a completion
    # time because doing so would invent history.
    booking = db.query(CabBooking).filter(CabBooking.id == booking_db_id).first()
    if booking:
        existing_types = {str(event.get("event_type")) for event in events}
        status_value = (
            booking.status.value
            if hasattr(booking.status, "value")
            else str(booking.status or "")
        ).lower()
        provider_event = (
            TimelineEventType.PROVIDER_REJECTED
            if status_value == BookingStatus.PROVIDER_REJECTED.value
            or str(booking.provider_response_status or "").lower() == "rejected"
            else TimelineEventType.PROVIDER_ACCEPTED
        )
        lifecycle = [
            (TimelineEventType.BOOKING_CREATED, booking.created_at),
            (provider_event, booking.provider_response_at),
            (TimelineEventType.DRIVER_ASSIGNED, booking.driver_assigned_at),
            (TimelineEventType.DRIVER_ACCEPTED, booking.driver_accepted_at),
            (TimelineEventType.TRIP_STARTED, booking.trip_started_at or booking.started_at),
            (TimelineEventType.TRIP_COMPLETED, booking.trip_completed_at or booking.completed_at),
        ]
        for index, (event_type, event_time) in enumerate(lifecycle, start=1):
            if not event_time or event_type.value in existing_types:
                continue
            events.append({
                "id": -(1_000_000_000 + booking_db_id * 10 + index),
                "event_type": event_type.value,
                "event_label": EVENT_LABELS[event_type],
                "event_time": event_time,
                "actor_id": None,
                "actor_type": "system",
                "metadata": {"derived_from_booking": True},
                "created_at": event_time,
            })
            existing_types.add(event_type.value)

    from app.db.models.driver_magic_link import DriverMagicLink
    magic_link = (
        db.query(DriverMagicLink)
        .filter(DriverMagicLink.booking_id == booking_db_id)
        .first()
    )
    if magic_link and magic_link.itinerary_stops:
        reached_by_stop = {
            event.stop_id: event for event in (magic_link.reach_events or [])
        }
        for stop in magic_link.itinerary_stops:
            stop_id = str(stop.get("id") or "")
            reached = reached_by_stop.get(stop_id)
            if not reached:
                # Unreached itinerary entries belong in the Planned Stops
                # panel, not in a chronological activity timeline.
                continue
            stop_type = (
                stop.get("type") or stop.get("stop_type") or "custom"
            ).lower()
            events.append({
                "id": -reached.id,
                "event_type": f"STOP_{stop_type.upper()}_REACHED",
                "event_label": (
                    f"{stop.get('name') or STOP_EVENT_LABELS.get(stop_type, 'Stop')} reached"
                ),
                "event_time": reached.reached_at,
                "actor_id": None,
                "actor_type": "stop",
                "metadata": {
                    "stop_id": stop_id,
                    "name": stop.get("name"),
                    "address": stop.get("address"),
                    "latitude": reached.latitude,
                    "longitude": reached.longitude,
                    "stop_type": stop_type,
                    "reached": True,
                    "notes": reached.notes,
                },
                "created_at": reached.reached_at,
            })

    def _to_naive(dt_val):
        if dt_val is None:
            return datetime.min
        if isinstance(dt_val, str):
            try:
                dt_val = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return datetime.min
        if isinstance(dt_val, datetime) and dt_val.tzinfo is not None:
            return dt_val.replace(tzinfo=None)
        if isinstance(dt_val, datetime):
            return dt_val
        return datetime.min

    events.sort(
        key=lambda event: (
            _to_naive(event.get("event_time") or event.get("created_at")),
            EVENT_SORT_ORDER.get(str(event.get("event_type")), 70),
            int(event.get("id") or 0),
        )
    )
    return events
