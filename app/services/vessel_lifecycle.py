"""Server-authoritative vessel lifecycle derived from ETD."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.db.models.vessel import Vessel
from app.db.models.vessel_call import VesselCall


DEPARTING_WINDOW = timedelta(hours=5)


def _aware_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def effective_vessel_status(
    vessel: Vessel,
    *,
    now: Optional[datetime] = None,
) -> str:
    if str(vessel.status or "").strip().lower() == "archived":
        return "Archived"
    etd = _aware_utc(vessel.etd)
    if etd is None:
        # Legacy rows may have a reviewed manual state but no ETD to derive
        # from. Preserve a valid state rather than silently reopening a vessel.
        stored = str(vessel.status or "").strip().lower()
        if stored == "departed":
            return "Departed"
        if stored == "departing":
            return "Departing"
        return "Active"
    current = _aware_utc(now) or datetime.now(timezone.utc)
    if current >= etd:
        return "Departed"
    if current >= etd - DEPARTING_WINDOW:
        return "Departing"
    return "Active"


def call_closed_by_the_clock(
    db: Session,
    vessel: Vessel,
    now: Optional[datetime] = None,
):
    """The vessel's last call, if this function closed it at the old ETD.

    `finish_vessel_call` stamps `ended_at` with the vessel's ETD, so a call
    whose end is exactly its own recorded ETD was closed by time passing rather
    than by anyone declaring the ship gone. When that ETD is later extended,
    the departure it recorded never happened and the call is reopened.

    Anything else is left alone: a call ended at some other moment was closed
    deliberately, and ARCHIVED or REASSIGNED calls are terminal regardless.

    Asking is separated from reopening so a dry run can report what an apply
    would do. A preview that has to guess at this drifts from the real thing,
    which on a script that writes to production is worse than no preview.
    """
    current = _aware_utc(now) or datetime.now(timezone.utc)
    last = (
        db.query(VesselCall)
        .filter(VesselCall.vessel_id == vessel.id)
        .order_by(VesselCall.id.desc())
        .first()
    )
    if last is None or last.ended_at is None:
        return None
    if str(last.status or "").upper() != "DEPARTED":
        return None

    ended_at = _aware_utc(last.ended_at)
    call_etd = _aware_utc(last.etd)
    if ended_at is None or call_etd is None or ended_at != call_etd:
        return None
    # Only while the new ETD genuinely puts the ship back in port.
    vessel_etd = _aware_utc(vessel.etd)
    if vessel_etd is None or vessel_etd <= current:
        return None
    return last


def _reopen_call_closed_by_the_clock(db: Session, vessel: Vessel, now: datetime):
    """Reopen the call `call_closed_by_the_clock` identifies, if there is one."""
    last = call_closed_by_the_clock(db, vessel, now)
    if last is None:
        return None
    last.ended_at = None
    last.etd = vessel.etd
    last.status = "ACTIVE"
    return last


def synchronize_vessel_lifecycle(
    db: Session,
    vessels: Iterable[Vessel],
    *,
    now: Optional[datetime] = None,
) -> int:
    """Persist derived states and finish calls without deleting history."""
    from app.services.historical_context import active_vessel_call, finish_vessel_call

    changed = 0
    current = _aware_utc(now) or datetime.now(timezone.utc)
    for vessel in vessels:
        status = effective_vessel_status(vessel, now=current)
        if vessel.status != status:
            vessel.status = status
            changed += 1

        call = active_vessel_call(db, vessel, create=False)
        if status == "Departed":
            if call is not None:
                changed += 1
                finish_vessel_call(
                    db,
                    vessel,
                    status="DEPARTED",
                    ended_at=_aware_utc(vessel.etd) or current,
                )
        elif status in {"Active", "Departing"} and vessel.agent_id is not None:
            if call is None:
                # The ship is in port with no open call. Two different causes,
                # and only one of them may open anything.
                #
                # A call this same function closed because the clock passed the
                # ETD is reopened when that ETD moves forward. The ship never
                # left — the departure was the estimate expiring, and extending
                # it says so. Leaving it closed stranded the vessel as Active
                # with no call at all, which is a state nothing else can use:
                # crew, trips and reports all hang off the call.
                #
                # Otherwise only ever open the *first* call for a vessel that
                # has none, backfilling records that predate vessel calls. A
                # vessel whose call was ended deliberately — departed by hand,
                # archived, reassigned — has sailed, and returning to port is a
                # deliberate act that goes through create_vessel.
                #
                # Either way this never creates a *second* call for a voyage
                # that is still the same one, which is what made an edited ETD
                # duplicate a vessel's crew roster.
                reopened = _reopen_call_closed_by_the_clock(db, vessel, current)
                if reopened is not None:
                    call = reopened
                    changed += 1
                else:
                    has_history = (
                        db.query(VesselCall.id)
                        .filter(VesselCall.vessel_id == vessel.id)
                        .first()
                        is not None
                    )
                    if not has_history:
                        call = active_vessel_call(db, vessel)
                        changed += 1
            if call is not None:
                if call.status != status.upper():
                    changed += 1
                call.status = status.upper()
    return changed
