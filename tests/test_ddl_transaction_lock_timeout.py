"""Schema guards must give up on a lock rather than hang the boot.

A deploy stalled at "Waiting for application startup." and was rolled back by the
platform after eleven failed health checks. The build was clean and nothing had
raised: the new container's `ALTER TABLE agent_profiles ADD COLUMN` was queued
behind a lock held by the outgoing container, and with no lock_timeout it would
have waited indefinitely. A retry minutes later succeeded only because those
connections had since gone.

The startup guards already log and carry on when their DDL raises. These tests
cover the part that made that handler unreachable — a blocked lock is not an
exception, it is silence.
"""

import time
import unittest

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db.session import ddl_transaction, engine


class DdlTransactionLockTimeoutTests(unittest.TestCase):
    def test_the_timeout_is_set_inside_the_transaction(self):
        with ddl_transaction("3s") as connection:
            setting = connection.execute(text("SHOW lock_timeout")).scalar()

        self.assertEqual(setting, "3s")

    def test_it_is_transaction_local_and_does_not_leak(self):
        """SET LOCAL, so an unrelated later connection is unaffected."""
        with ddl_transaction("3s"):
            pass

        with engine.connect() as connection:
            self.assertNotEqual(
                connection.execute(text("SHOW lock_timeout")).scalar(), "3s"
            )

    def test_a_blocked_alter_raises_instead_of_waiting(self):
        """The case that rolled the deploy back, reproduced in miniature."""
        blocker = engine.connect()
        blocker.begin()
        blocker.execute(text("LOCK TABLE agent_profiles IN ACCESS EXCLUSIVE MODE"))
        try:
            started = time.monotonic()
            with self.assertRaises(OperationalError) as caught:
                with ddl_transaction("1s") as connection:
                    connection.execute(text(
                        "ALTER TABLE agent_profiles "
                        "ADD COLUMN IF NOT EXISTS _lock_probe integer"
                    ))
            elapsed = time.monotonic() - started
        finally:
            blocker.rollback()
            blocker.close()

        self.assertIn("lock timeout", str(caught.exception.orig).lower())
        # Bounded, and nowhere near a readiness probe's patience.
        self.assertLess(elapsed, 10)

    def tearDown(self):
        # The ALTER above is rolled back with its transaction, but a future
        # change to that test should not be able to leave the column behind.
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE agent_profiles DROP COLUMN IF EXISTS _lock_probe"
            ))


if __name__ == "__main__":
    unittest.main()
