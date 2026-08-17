"""One passport, one account — and what counts as a passport.

Sign-up validated the email and the mobile number and nothing else, so a
passport typed to get past the field was accepted and then became part of the
HPID, which is permanent. Production holds accounts under `U` and
`NOT_PROVIDED`, giving identities like `HP-U-IN-VIS`; three different people
share the first of those.

That is also what blocks a uniqueness rule. The duplicates are not people who
registered twice — an audit found no two accounts sharing both a passport and a
name — they are placeholders colliding with each other. Refusing them at the
door is what makes the constraint reachable.

Runs against the configured database inside a transaction that is always
rolled back.
"""

import unittest
import uuid

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy.orm import Session

from app.db.models.crew_profile import CrewProfile
from app.db.models.user import User
from app.db.session import engine
from app.services.crew_identity import (
    CrewIdentityConflict,
    passport_already_registered,
    validate_passport_number,
)


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _passport():
    """A passport no other row in the shared test database is using.

    These run against the configured database rather than an empty one, so a
    hard-coded value collides with whatever production-like data is seeded
    there — and a uniqueness test that finds someone else's row proves nothing.
    """
    return f"Z{uuid.uuid4().int % 10 ** 8:08d}"


class PassportValidationTests(unittest.TestCase):
    """No database needed: these are rules about the value itself."""

    def test_a_real_passport_is_returned_canonically(self):
        self.assertEqual(validate_passport_number("  u3387056 "), "U3387056")

    def test_the_placeholders_production_actually_holds_are_refused(self):
        for value in ("NOT_PROVIDED", "not provided", "U", "n/a", "NIL", "000000"):
            with self.subTest(value=value):
                with self.assertRaises(CrewIdentityConflict):
                    validate_passport_number(value)

    def test_a_single_character_is_not_a_passport(self):
        """The `U` accounts: one keystroke, three different people."""
        with self.assertRaises(CrewIdentityConflict):
            validate_passport_number("U")

    def test_something_too_short_is_refused(self):
        with self.assertRaises(CrewIdentityConflict):
            validate_passport_number("AB12")

    def test_letters_alone_are_refused(self):
        """Every national format carries digits; a word here is a placeholder."""
        with self.assertRaises(CrewIdentityConflict):
            validate_passport_number("PASSPORT")

    def test_a_missing_passport_is_refused_rather_than_defaulted(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                with self.assertRaises(CrewIdentityConflict):
                    validate_passport_number(value)

    def test_a_long_numeric_passport_is_accepted(self):
        """Production holds these; the rule must not reject real crew."""
        self.assertEqual(validate_passport_number("768947389275"), "768947389275")


class PassportUniquenessTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def profile(self, passport):
        user = User(email=_uniq("crew") + "@example.com",
                    hashed_password="x", role="crew")
        self.db.add(user)
        self.db.flush()
        profile = CrewProfile(
            user_id=user.id, full_name="Crew", rank="able_seaman",
            nationality="IN", hpid=_uniq("HP"), passport_number=passport,
        )
        self.db.add(profile)
        self.db.flush()
        return profile

    def test_a_second_account_on_one_passport_is_found(self):
        passport = _passport()
        existing = self.profile(passport)

        found = passport_already_registered(self.db, passport)

        self.assertEqual(found.id, existing.id)

    def test_spacing_and_case_do_not_hide_a_duplicate(self):
        """Legacy rows hold spaces; a duplicate must not slip through on one."""
        passport = _passport()
        existing = self.profile(f"{passport[:3]} {passport[3:]}")

        found = passport_already_registered(self.db, passport.lower())

        self.assertEqual(found.id, existing.id)

    def test_an_unused_passport_is_free(self):
        self.profile(_passport())

        self.assertIsNone(passport_already_registered(self.db, _passport()))

    def test_the_account_being_edited_is_not_its_own_duplicate(self):
        passport = _passport()
        existing = self.profile(passport)

        found = passport_already_registered(
            self.db, passport, exclude_profile_id=existing.id)

        self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
