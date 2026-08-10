"""Linking a vessel's manifest rows to the crew profiles that own the records.

A VesselCrew row is what the agent uploaded; a CrewProfile is the account the
crew member signed in with. Everything a report wants to count — shore passes,
cab trips, SOS alerts — hangs off the profile, so a report is only as complete
as this join.

Matching on HPID alone is not enough. HPID is generated from passport plus
nationality, so a manifest that spells the nationality differently from the
crew member's own registration produces a different HPID for the same person
(the historical IN/IND mismatch), and their records silently drop out of every
report. `_resolve_vessel_for_crew` in routes_incidents already walks
HPID -> passport -> vessel name for the profile -> vessel direction; this is the
same ladder in the vessel -> profiles direction.
"""
from typing import List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models.crew_profile import CrewProfile
from app.db.models.vessel_crew import VesselCrew


def _normalized(values) -> List[str]:
    return sorted({str(v).strip().upper() for v in values if v and str(v).strip()})


def vessel_crew_profiles(db: Session, vessel) -> List[CrewProfile]:
    """Every crew profile belonging to `vessel`'s manifest.

    Ordered by id so callers get a stable result. Returns [] for a vessel whose
    manifest has no registered crew.
    """
    manifest = db.query(VesselCrew).filter(VesselCrew.vessel_id == vessel.id).all()
    hp_ids = _normalized(row.hp_id for row in manifest)
    passports = _normalized(row.passport_number for row in manifest)

    clauses = []
    if hp_ids:
        clauses.append(func.upper(func.trim(CrewProfile.hpid)).in_(hp_ids))
    if passports:
        clauses.append(func.upper(func.trim(CrewProfile.passport_number)).in_(passports))
    # Crew who registered before ever being put on a manifest may carry neither
    # a matching HPID nor a passport, but did name their ship.
    if vessel.name:
        clauses.append(func.upper(func.trim(CrewProfile.vessel)) == vessel.name.strip().upper())

    if not clauses:
        return []
    return db.query(CrewProfile).filter(or_(*clauses)).order_by(CrewProfile.id).all()


def vessel_crew_profile_ids(db: Session, vessel) -> List[int]:
    return [profile.id for profile in vessel_crew_profiles(db, vessel)]


def profile_id_by_hpid(profiles) -> dict:
    """HPID -> profile id, for resolving the HPIDs typed into a group booking."""
    return {
        profile.hpid.strip().upper(): profile.id
        for profile in profiles
        if profile.hpid and profile.hpid.strip()
    }


def resolve_hpid(mapping: dict, hpid: Optional[str]) -> Optional[int]:
    """Look up a booking-supplied HPID the same way it was indexed."""
    if not hpid:
        return None
    return mapping.get(str(hpid).strip().upper())


def eligible_profile_ids(db: Session, vessel, profiles) -> set:
    """Of `profiles`, those the manifest marks eligible for shore leave.

    Eligibility is a property of the manifest row, not the account, so it has
    to be carried across the same identity join used to find the profiles.
    """
    eligible_rows = db.query(VesselCrew).filter(
        VesselCrew.vessel_id == vessel.id,
        VesselCrew.shore_pass_eligible.is_(True),
    ).all()
    keys = set(_normalized(row.hp_id for row in eligible_rows))
    keys |= set(_normalized(row.passport_number for row in eligible_rows))
    if not keys:
        return set()

    matched = set()
    for profile in profiles:
        identifiers = _normalized([profile.hpid, profile.passport_number])
        if keys.intersection(identifiers):
            matched.add(profile.id)
    return matched
