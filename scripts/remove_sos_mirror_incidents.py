"""Delete the Incident rows that used to be mirrored from every crew SOS.

Raising an SOS once created a CrewSos row *and* a copycat Incident titled
"SOS Alert". Nothing linked the two, so one emergency showed up twice — on the
SOS page and in Incident Management — and closing the SOS left the Incident
open forever. The mirror is gone from the SOS endpoint; this clears the rows it
already wrote.

Only rows carrying the mirror's exact signature are touched: type CREW, title
"SOS Alert", and the generated description. Incidents an agent genuinely filed
about an SOS are worded differently and are left alone.

Usage (from onemarinex-backend/):
    PYTHONPATH=. ./.venv/bin/python scripts/remove_sos_mirror_incidents.py
    PYTHONPATH=. ./.venv/bin/python scripts/remove_sos_mirror_incidents.py --apply

Without --apply it only reports what it would delete.
"""
import argparse
import sys

from app.db.session import SessionLocal
from app.db.models.incident import Incident, IncidentType


def find_mirrors(db):
    return db.query(Incident).filter(
        Incident.type == IncidentType.CREW,
        Incident.title == "SOS Alert",
        Incident.description.like("SOS triggered by %"),
    ).order_by(Incident.id).all()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="actually delete; otherwise just report")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        mirrors = find_mirrors(db)
        if not mirrors:
            print("No SOS-mirrored incidents found.")
            return 0

        print(f"{len(mirrors)} SOS-mirrored incident(s):")
        for incident in mirrors:
            status = getattr(incident.status, "value", incident.status)
            print(f"  #{incident.id}  {incident.incident_id}  {status}  {incident.created_at}")

        if not args.apply:
            print("\nDry run. Re-run with --apply to delete these rows.")
            return 0

        # Notes and timeline events point at incidents with a plain FK, so they
        # have to go first or the delete violates the constraint.
        from app.db.models.incident import IncidentNote, IncidentTimelineEvent

        ids = [incident.id for incident in mirrors]
        notes = db.query(IncidentNote).filter(IncidentNote.incident_id.in_(ids)).delete(
            synchronize_session=False)
        events = db.query(IncidentTimelineEvent).filter(
            IncidentTimelineEvent.incident_id.in_(ids)).delete(synchronize_session=False)
        removed = db.query(Incident).filter(Incident.id.in_(ids)).delete(
            synchronize_session=False)
        db.commit()
        print(f"\nDeleted {removed} incident(s), {notes} note(s), {events} timeline event(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
