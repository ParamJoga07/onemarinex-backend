"""Shared SQLAlchemy column types."""

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """A `TIMESTAMP WITHOUT TIME ZONE` column whose values are always UTC.

    Some tables store naive datetimes written by `datetime.utcnow()`. The values
    are correct UTC instants, but because they carry no offset, FastAPI
    serialised them as `2026-08-09T06:05:12` with no trailing `Z` — and a
    browser reads an offset-less string as *local* time. An agent in India saw
    every incident dated 5 hours 30 minutes off, while SOS alerts (stored in
    timezone-aware columns) were correct on the same screen.

    This attaches the UTC offset on the way out and strips it on the way in, so
    the API always emits an unambiguous instant. The underlying column type is
    unchanged, so no migration and no data rewrite is needed — the stored values
    were already UTC, they simply never said so.

    Tables that already use `DateTime(timezone=True)` need none of this.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Normalise to naive UTC before storing."""
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        """Label the stored value as UTC on the way out."""
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
