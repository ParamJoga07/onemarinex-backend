"""Which vessel a crew member sails on, and who to call about their trip.

Two things a booking needs to record and could not previously resolve:

*The vessel.* `cab_bookings` stores only `crew_id`, so a trip's ship has to be
inferred from whoever booked it. Inferring it at *read* time is what let a crew
member's trips move between ships when they joined a new one — they are on both
manifests, so both vessels claim their whole history. Resolving it once, when
the booking is made, pins the trip to the ship the crew member was actually on.

*The agency contact.* `agent_number` used to be filled from
`port_rules.helpline_number`, which is the *port's* number, owned by the
superadmin and shared by every agency berthed there. So the "agent number" on a
trip was never the agent's, could not be changed by them, and stayed frozen at
whatever the port had configured. The agency's own number lives on
`agent_profiles.support_number` — which the port-rules screen already writes
when an agent edits it — and that is what belongs here.
"""
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session


def vessel_for_crew(db: Session, crew) -> Optional[object]:
    """The vessel whose manifest lists this crew member, or None.

    HPID first, then passport — the same ladder used elsewhere, because an HPID
    regenerated from a differently-spelled nationality will not match while the
    passport still does. Falls back to the ship named on the profile, which is
    all a crew member who has not yet been put on a manifest can offer.
    """
    from app.db.models.vessel import Vessel
    from app.db.models.vessel_crew import VesselCrew

    if crew is None:
        return None

    identity = []
    if crew.hpid:
        identity.append(func.upper(func.trim(VesselCrew.hp_id)) == crew.hpid.strip().upper())
    if crew.passport_number:
        identity.append(
            func.upper(func.trim(VesselCrew.passport_number))
            == crew.passport_number.strip().upper()
        )

    if identity:
        match = (
            db.query(Vessel)
            .join(VesselCrew, VesselCrew.vessel_id == Vessel.id)
            .filter(or_(*identity))
            .first()
        )
        if match:
            return match

    if crew.vessel:
        return (
            db.query(Vessel)
            .filter(func.upper(func.trim(Vessel.name)) == crew.vessel.strip().upper())
            .first()
        )
    return None


def support_number_for_crew(db: Session, crew) -> Optional[str]:
    """The agency's contact number for this crew member's vessel.

    Returns None rather than a placeholder when the agency has not set one: on
    a contact row an invented number is worse than an honest blank.
    """
    from app.db.models.user import User

    vessel = vessel_for_crew(db, crew)
    if vessel is None or not vessel.agent_id:
        return None
    agent = db.query(User).filter(User.id == vessel.agent_id).first()
    profile = getattr(agent, "agent_profile", None) if agent else None
    number = getattr(profile, "support_number", None) if profile else None
    return (number or "").strip() or None
