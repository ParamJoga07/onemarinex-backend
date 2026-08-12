"""Server-authoritative vessel lifecycle derived from ETD."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.db.models.vessel import Vessel


DEPARTING_WINDOW = timedelta(hours=24)


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
                call = active_vessel_call(db, vessel)
                changed += 1
            if call is not None:
                if call.status != status.upper():
                    changed += 1
                call.status = status.upper()
    return changed
