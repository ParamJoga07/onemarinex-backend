"""Linking a vessel's manifest rows to the crew profiles that own the records.

A VesselCrew row is what the agent uploaded; a CrewProfile is the account the
crew member signed in with. Everything a report wants to count — shore passes,
cab trips, SOS alerts — hangs off the profile, so a report is only as complete
as this join.

Matching on HPID alone is not enough. HPID is generated from passport plus
nationality, so a manifest that spells the nationality differently from the
crew member's own registration produces a different HPID for the same person
(the historical IN/IND mismatch), and their records silently drop out of every
report. Passport closes that gap.

What this deliberately does *not* answer is which vessel a past record belongs
to. A crew member who sails on one ship and later joins another is on both
manifests, so both vessels match them here — correctly, because they really
were crew on both. Attributing an SOS or a trip by asking who is on the
manifest therefore drags their whole history onto whichever ship they joined
most recently. Records carrying their own vessel stamp must be attributed by
that stamp; this join is only the fallback for rows written before the stamp
existed. See `vessel_matches_record` below.
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

    # Both clauses are scoped to *this* vessel's manifest, so they answer
    # "is this person on the crew list" and nothing wider.
    #
    # There used to be a third clause matching CrewProfile.vessel against the
    # vessel name. It was the one that over-reached: it claimed any profile
    # naming this ship whether or not the manifest listed them. Measured across
    # the local fleet it pulled in a profile that was on no manifest, while
    # recovering nobody the passport clause had not already found.
    clauses = []
    if hp_ids:
        clauses.append(func.upper(func.trim(CrewProfile.hpid)).in_(hp_ids))
    if passports:
        clauses.append(func.upper(func.trim(CrewProfile.passport_number)).in_(passports))

    if not clauses:
        return []
    return db.query(CrewProfile).filter(or_(*clauses)).order_by(CrewProfile.id).all()


def vessel_crew_profile_ids(db: Session, vessel) -> List[int]:
    return [profile.id for profile in vessel_crew_profiles(db, vessel)]


class RosterMember:
    """One person on a vessel's crew list.

    Counting people ashore used to key on the crew *profile* — the account they
    signed in with. Anyone on the manifest who had never registered therefore
    had no id to count, and silently vanished: a cab booked for three came out
    as one person ashore, because only the crew member who did the booking had
    an account.

    `key` is a stable identity that exists whether or not they registered, so
    the manifest decides who is aboard and the account is only how their own
    records are found.
    """

    __slots__ = ("key", "profile_id", "hpid", "name", "eligible")

    def __init__(self, key, profile_id, hpid, name, eligible):
        self.key = key
        self.profile_id = profile_id
        self.hpid = hpid
        self.name = name
        self.eligible = eligible


class VesselRoster:
    """A vessel's crew list, with the lookups a report needs."""

    def __init__(self, members: List[RosterMember]):
        self.members = members
        self.profile_ids = [m.profile_id for m in members if m.profile_id]
        self._key_by_profile = {m.profile_id: m.key for m in members if m.profile_id}
        self._key_by_hpid = {m.hpid: m.key for m in members if m.hpid}
        self.eligible_keys = {m.key for m in members if m.eligible}

    def key_for_profile(self, profile_id) -> Optional[str]:
        return self._key_by_profile.get(profile_id)

    def key_for_hpid(self, hpid) -> Optional[str]:
        if not hpid:
            return None
        return self._key_by_hpid.get(str(hpid).strip().upper())

    def __len__(self):
        return len(self.members)


def vessel_roster(db: Session, vessel) -> VesselRoster:
    """Everyone on `vessel`'s manifest, registered or not."""
    manifest = db.query(VesselCrew).filter(VesselCrew.vessel_id == vessel.id).all()
    profiles = vessel_crew_profiles(db, vessel)

    by_hpid = {}
    by_passport = {}
    for profile in profiles:
        if profile.hpid and profile.hpid.strip():
            by_hpid[profile.hpid.strip().upper()] = profile
        if profile.passport_number and profile.passport_number.strip():
            by_passport[profile.passport_number.strip().upper()] = profile

    members = []
    for row in manifest:
        hpid = (row.hp_id or "").strip().upper() or None
        passport = (row.passport_number or "").strip().upper() or None
        profile = (by_hpid.get(hpid) if hpid else None) or (
            by_passport.get(passport) if passport else None
        )
        members.append(RosterMember(
            # HPID is the identity the rest of the system types and stores;
            # the manifest row id only stands in when a row has none.
            key=hpid or f"manifest:{row.id}",
            profile_id=profile.id if profile else None,
            hpid=hpid,
            name=row.name,
            eligible=bool(row.shore_pass_eligible),
        ))
    return VesselRoster(members)


def vessel_call_roster(db: Session, vessel_call) -> VesselRoster:
    """Historical crew roster captured by one immutable vessel call."""
    from app.db.models.crew_assignment import CrewAssignment

    assignments = db.query(CrewAssignment).filter(
        CrewAssignment.vessel_call_id == vessel_call.id
    ).order_by(CrewAssignment.id).all()
    members = []
    for row in assignments:
        hpid = (row.hpid or "").strip().upper() or None
        members.append(RosterMember(
            key=hpid or f"assignment:{row.id}",
            profile_id=row.crew_profile_id,
            hpid=hpid,
            name=row.crew_name,
            eligible=bool(row.shore_pass_eligible),
        ))
    return VesselRoster(members)


def vessel_matches_record(vessel, stamped_vessel: Optional[str]) -> Optional[bool]:
    """Does a record stamped `stamped_vessel` belong to `vessel`?

    Returns True/False when the record names a vessel, and None when it does not
    — the caller then falls back to manifest linkage, which is all a row written
    before the stamp existed can offer.

    Compared case- and whitespace-insensitively because the stamp is a free
    string copied from the crew profile, not a foreign key.
    """
    stamp = (stamped_vessel or "").strip().upper()
    if not stamp:
        return None
    return stamp == (vessel.name or "").strip().upper()


def filter_records_for_vessel(vessel, records, stamp_of) -> list:
    """Keep the records belonging to `vessel`.

    `stamp_of` reads the vessel name off one record. Records naming a different
    vessel are dropped; records naming none are kept, since manifest linkage is
    the only signal they have.
    """
    kept = []
    for record in records:
        verdict = vessel_matches_record(vessel, stamp_of(record))
        if verdict is False:
            continue
        kept.append(record)
    return kept
