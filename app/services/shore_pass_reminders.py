"""Periodic job: WhatsApp reminders as a crew member's shore pass approaches
expiry. Runs outside any request context (invoked by the APScheduler job in
app/main.py), so it owns its own DB session rather than using get_db().
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.db.models.shore_pass import ShorePass
from app.db.models.shore_pass_reminder import ShorePassReminder
from app.db.models.crew_profile import CrewProfile
from app.services.whatsapp import notify_return_reminder, notify_critical_return_reminder

logger = logging.getLogger(__name__)


def _attempt(db, shore_pass: ShorePass, reminder_type: str, notify_fn) -> None:
    # Insert the dedup row *before* sending — race-safe across multiple app
    # instances, and stops us from retrying every poll tick if the crew
    # member simply has no phone number on file.
    db.add(ShorePassReminder(shore_pass_id=shore_pass.id, reminder_type=reminder_type))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return  # already sent, by us or another instance

    crew_profile = db.query(CrewProfile).filter(CrewProfile.id == shore_pass.crew_profile_id).first()
    phone = crew_profile.user.mobile_number if crew_profile and crew_profile.user else None
    try:
        notify_fn(phone)
    except Exception:
        logger.exception("WhatsApp %s notify failed for shore_pass %s", reminder_type, shore_pass.id)


def run_shore_pass_reminders() -> None:
    db = SessionLocal()
    try:
        # Deliberately NOT keying off in_time IS NULL — verify_shorepass() sets
        # in_time = expires_at immediately at verification (a separate,
        # pre-existing quirk), so status + expires_at proximity is the only
        # reliable "still within shore leave" signal today.
        now = datetime.now()
        passes = db.query(ShorePass).filter(
            ShorePass.status == "approved",
            ShorePass.expires_at.isnot(None),
            ShorePass.expires_at > now,
        ).all()

        for shore_pass in passes:
            # ShorePass.expires_at is a DateTime(timezone=True) column, so it
            # comes back tz-aware even though it was written from a naive
            # datetime.now() in verify_shorepass() — strip tzinfo before doing
            # naive arithmetic against `now`, which uses the same convention.
            expires_at = shore_pass.expires_at
            if expires_at.tzinfo is not None:
                expires_at = expires_at.replace(tzinfo=None)
            remaining = expires_at - now
            if remaining <= timedelta(minutes=30):
                _attempt(db, shore_pass, "critical_30m", notify_critical_return_reminder)
            elif remaining <= timedelta(hours=2):
                _attempt(db, shore_pass, "return_2h", notify_return_reminder)
    except Exception:
        logger.exception("run_shore_pass_reminders failed")
    finally:
        db.close()
