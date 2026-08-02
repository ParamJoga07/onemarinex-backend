"""Deploy-time database migration entrypoint.

Run this before the web process starts::

    python -m app.db.migrate

Why this exists instead of a plain ``alembic upgrade head``
----------------------------------------------------------
This project's migration history cannot be replayed from base. The earliest
revision alters ``rfqs`` / ``rfq_quotes`` / ``vendor_profiles`` — tables from a
retired marketplace product — without guarding for their absence. Against an
empty database it fails with ``UndefinedTable: relation "rfq_quotes" does not
exist``; against a database built by ``create_all()`` it fails later on a
``ports_served`` type cast. Neither path can reach head.

What has always actually built the schema is ``Base.metadata.create_all()`` at
app startup, which produces a schema equivalent to head. So Alembic is usable
only as a series of deltas applied *from a baseline*, never as a replay from
zero. This module establishes that baseline and then applies deltas:

* No ``alembic_version`` row -> create the schema from the models, then stamp
  head. No migration DDL runs, so there is nothing to fail.
* Already stamped -> ``upgrade head`` normally.

Stamping skips whatever the historical revisions did that the models do not
express. Measured against a create_all-built database that is the
``port_configs`` table and four ``cab_bookings`` columns (``accepted_at``,
``planned_return_time``, ``rating``, ``ride_class``) — none of which appear in
any model or anywhere in application code.
"""

import logging
import os
import sys
from contextlib import contextmanager
from typing import Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.db.base import Base  # noqa: F401 — registers every model on Base
from app.db.session import engine

log = logging.getLogger("app.migrate")

# Any 64-bit constant works; it only has to be stable across deploys so two
# instances starting together serialize instead of racing on DDL.
_ADVISORY_LOCK_KEY = 8_274_119_035_641_772


def _alembic_config() -> Config:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config = Config(os.path.join(root, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(root, "alembic"))
    return config


def current_revision() -> Optional[str]:
    """The stamped revision, or None if this database has never been stamped."""
    with engine.connect() as connection:
        if not inspect(connection).has_table("alembic_version"):
            return None
        row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
        return row[0] if row else None


@contextmanager
def _deploy_lock():
    """Serialize schema work across concurrently starting instances.

    Session-level advisory lock on its own connection, held for the whole
    operation. Alembic runs on its own connections, which this does not block.
    """
    lock_connection = engine.connect()
    try:
        lock_connection.execute(
            text("SELECT pg_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY}
        )
        lock_connection.commit()
        yield
    finally:
        try:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY}
            )
            lock_connection.commit()
        finally:
            lock_connection.close()


def baseline_if_unstamped() -> bool:
    """Stamp an unstamped database at head. Returns True if it stamped.

    Deliberately never upgrades: this also runs at web startup, where a long
    migration would stall boot and fail health checks. Applying deltas is the
    pre-deploy job's job. Stamping is a single INSERT, so it is safe to run on
    every boot.
    """
    with _deploy_lock():
        if current_revision() is not None:
            return False

        log.info("no alembic_version found — baselining this database")
        # Safe on an existing database: create_all only issues CREATE TABLE for
        # tables that are absent, and never alters one that is present.
        Base.metadata.create_all(bind=engine)
        command.stamp(_alembic_config(), "head")
        log.info("database baselined at head; no migration DDL was run")
        return True


def run_migrations() -> None:
    if baseline_if_unstamped():
        return

    with _deploy_lock():
        revision = current_revision()
        log.info("database stamped at %s — upgrading to head", revision)
        command.upgrade(_alembic_config(), "head")
        log.info("migrations applied; now at %s", current_revision())


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        run_migrations()
    except Exception:
        log.exception("migration failed — aborting before the app starts")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
