"""Who is off the ship right now.

The dashboard tile and the shore leave report were answering this from
different evidence, so they disagreed in front of the agent. The dashboard
counted shore passes with a sign-out and no sign-in; the report also treats a
cab trip that actually started as proof its crew went ashore.

That gap is visible whenever crew leave by cab without a shore pass: the trip
is underway, the report knows they are ashore, and the tile reads zero. It also
counted pass *rows* rather than people, so a crew member with two open passes
counted twice.

One calculation, used by both.
"""
from typing import Iterable, Optional, Set

from sqlalchemy.orm import Session

from app.db.models.cab_booking import BookingStatus, CabBooking
from app.db.models.shore_pass import ShorePass

# A trip is only evidence of being ashore once it has actually begun. Driver
# assigned, accepted and arrived all mean the crew are still aboard waiting.
_ENDED_TRIP_STATUSES = {BookingStatus.COMPLETED, BookingStatus.CANCELLED}


def crew_ashore_ids(
    db: Session,
    crew_profile_ids: Iterable[int],
    *,
    extra_people=None,
) -> Set[int]:
    """Distinct crew with an open departure — an unfinished pass or trip.

    `extra_people` resolves a booking to everyone it carried, so group
    passengers count individually rather than only the crew member who booked.
    It takes a CabBooking and returns an iterable of crew profile ids; when it
    is not given, only the booking's own crew member is counted.

    Deduplicated, so someone with both an open pass and a running trip is one
    person ashore, not two.
    """
    ids = [i for i in crew_profile_ids if i]
    if not ids:
        return set()

    ashore: Set[int] = {
        row[0] for row in db.query(ShorePass.crew_profile_id).filter(
            ShorePass.crew_profile_id.in_(ids),
            ShorePass.out_time.isnot(None),
            ShorePass.in_time.is_(None),
        ).all()
        if row[0]
    }

    running = db.query(CabBooking).filter(
        CabBooking.crew_id.in_(ids),
        CabBooking.status.notin_(list(_ENDED_TRIP_STATUSES)),
    ).all()
    for trip in running:
        if not (trip.trip_started_at or trip.started_at):
            # Booked, driver maybe assigned — nobody has left the ship yet.
            continue
        if extra_people is not None:
            ashore.update(person for person in extra_people(trip) if person)
        elif trip.crew_id:
            ashore.add(trip.crew_id)

    return ashore


def crew_ashore_count(
    db: Session,
    crew_profile_ids: Iterable[int],
    *,
    extra_people=None,
) -> int:
    """How many crew are ashore, counting the seats a cab could not name.

    The shore leave report counts a booking as putting `num_passengers` people
    ashore, because most of a ship's company has no account and group bookings
    name nobody but the booker. This tile has to agree with it: an agent seeing
    "1 crew ashore" beside a report reading "8 went ashore" for the same vessel
    and the same day has no way to tell which is lying.

    Named crew are counted by identity, so someone with both an open pass and a
    running trip is one person. Only the remainder of each trip's seats is added
    on top, which is the same `max(named, num_passengers)` the report applies.
    """
    named = crew_ashore_ids(db, crew_profile_ids, extra_people=extra_people)

    ids = [i for i in crew_profile_ids if i]
    if not ids:
        return len(named)

    unnamed_seats = 0
    running = db.query(CabBooking).filter(
        CabBooking.crew_id.in_(ids),
        CabBooking.status.notin_(list(_ENDED_TRIP_STATUSES)),
    ).all()
    for trip in running:
        if not (trip.trip_started_at or trip.started_at):
            continue
        on_this_trip = (
            len({person for person in extra_people(trip) if person})
            if extra_people is not None
            else (1 if trip.crew_id else 0)
        )
        unnamed_seats += max(0, (trip.num_passengers or 0) - on_this_trip)

    return len(named) + unnamed_seats
