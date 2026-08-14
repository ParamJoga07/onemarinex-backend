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
from sqlalchemy.orm import Session


def support_number_for_assignment(db: Session, assignment) -> Optional[str]:
    """The agency's contact number for this crew member's vessel.

    Returns None rather than a placeholder when the agency has not set one: on
    a contact row an invented number is worse than an honest blank.
    """
    call = getattr(assignment, "vessel_call", None) if assignment else None
    if call is None or call.agency_id is None:
        return None
    from app.db.models.agent_profile import AgentProfile

    profile = db.query(AgentProfile).filter(AgentProfile.id == call.agency_id).first()
    number = getattr(profile, "support_number", None) if profile else None
    return (number or "").strip() or None
