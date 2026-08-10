import uuid


def generate_hpid(passport_number: str, nationality: str, port: str) -> str:
    """
    Generate HPID using pattern: HP-{passport_number}-{NAT}-{PORT}
    Examples: HP-P1234567-IND-MUM, HP-P7654321-PHI-DUB
    """
    # Use upper case passport number
    id_part = str(passport_number).strip().upper() if passport_number else "XXXX"

    # First 3 chars of nationality
    nat_part = str(nationality)[:3].upper() if nationality else "GEN"

    # First 3 chars of port (stripping 'port_' prefix if present)
    port_part = str(port).replace("port_", "")[:3].upper() if port else "GEN"

    return f"HP-{id_part}-{nat_part}-{port_part}"


def generate_unique_hpid(db, passport_number, nationality, port, unique_fallback=None, exclude_profile_id=None) -> str:
    """
    Same HP-{...}-{NAT}-{PORT} pattern as generate_hpid(), but guaranteed
    unique against CrewProfile.hpid (a unique-constrained column).

    generate_hpid() alone falls back to the literal "XXXX" whenever
    passport_number is missing, which is IDENTICAL for every crew member
    sharing the same nationality and port — any two such crew members
    collide and the second one's save fails with a UniqueViolation.
    Disambiguate with unique_fallback (e.g. the crew's user_id, which is
    stable per crew member) whenever passport_number is missing, and fall
    back to a random suffix as a last resort if a collision still exists.
    """
    from app.db.models.crew_profile import CrewProfile

    candidate = generate_hpid(passport_number, nationality, port)
    if not passport_number or not str(passport_number).strip():
        disambiguator = unique_fallback if unique_fallback is not None else uuid.uuid4().hex[:8]
        candidate = f"{candidate}-{disambiguator}"

    query = db.query(CrewProfile).filter(CrewProfile.hpid == candidate)
    if exclude_profile_id is not None:
        query = query.filter(CrewProfile.id != exclude_profile_id)
    if query.first() is not None:
        candidate = f"{candidate}-{uuid.uuid4().hex[:4].upper()}"
    return candidate


def ensure_stable_hpid(db, profile, *, port=None) -> str:
    """Issue an HPID once and never derive a replacement from mutable profile data.

    Passport, nationality, vessel and port can legitimately change. They may be
    used as readable ingredients when an identifier is first issued, but cannot
    be allowed to change an identifier that is already referenced by incidents,
    manifests, shore passes and historical reports.
    """
    if profile.hpid:
        return profile.hpid
    profile.hpid = generate_unique_hpid(
        db,
        profile.passport_number,
        profile.nationality,
        port or profile.current_port or "port_general",
        unique_fallback=profile.user_id,
        exclude_profile_id=profile.id,
    )
    return profile.hpid
