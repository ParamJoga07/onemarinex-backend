"""Average shore leave duration, and which day a trip belongs to.

Two defects motivated these tests.

The average summed cab minutes only, then divided by a headcount that also
included crew who walked out on a shore pass without booking a cab. Those people
sat in the denominator and contributed nothing to the numerator, so any day
mixing the two read low.

Separately, trips were selected by `created_at` while shore passes were selected
by `out_time`. The two disagreed across midnight: a cab booked at 23:50 and
driven after midnight was reported on the day it was booked.

Runs against the configured database inside a transaction that is always rolled
back, so it leaves no rows behind.
"""

from datetime import datetime
import unittest
import uuid
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import app.db.base  # noqa: F401 — registers every model on Base
from sqlalchemy.orm import Session

from app.api.v1.routes_agents import shore_leave_report
from app.db.models.cab_booking import BookingStatus, CabBooking
from app.db.models.crew_profile import CrewProfile
from app.db.models.shore_pass import ShorePass
from app.db.models.user import User
from app.db.models.vessel import Vessel
from app.db.models.vessel_crew import VesselCrew
from app.db.session import engine

REPORT_DATE = "2026-03-05"

# The reporting window is a calendar day *at the port*, and a vessel with no
# configured port falls back to Asia/Kolkata. Times here are therefore written
# on the port's clock: expressing them in UTC makes the midnight cases silently
# vacuous, because 23:50 UTC on the 4th is already 05:20 on the 5th at the port.
PORT_TZ = ZoneInfo("Asia/Kolkata")


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _at(hour, minute=0, day=5):
    """An instant on the reporting day, on the port's clock."""
    return datetime(2026, 3, day, hour, minute, tzinfo=PORT_TZ)


class ShoreLeaveAverageTests(unittest.TestCase):
    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.db = Session(bind=self.connection)

        self.agent_user = User(
            email=_uniq("agent") + "@example.com", hashed_password="x", role="agent"
        )
        self.db.add(self.agent_user)
        self.db.flush()

        self.vessel = Vessel(
            agent_id=self.agent_user.id, name=_uniq("MV"), imo_number=_uniq("IMO"),
            vessel_type="Bulk Carrier", status="Active",
        )
        self.db.add(self.vessel)
        self.db.flush()

        self.agent = SimpleNamespace(
            id=self.agent_user.id, role="agent",
            agent_profile=SimpleNamespace(
                assigned_port=None, agency_name="Test Agency", agency_logo_url=None,
            ),
        )

    def tearDown(self):
        self.db.close()
        self.trans.rollback()
        self.connection.close()

    def crew(self, shore_pass_eligible=True):
        """One crew member on this vessel's manifest."""
        crew_user = User(
            email=_uniq("crew") + "@example.com", hashed_password="x", role="crew"
        )
        self.db.add(crew_user)
        self.db.flush()
        hpid = _uniq("HP")
        profile = CrewProfile(
            user_id=crew_user.id, full_name="Crew", rank="able_seaman",
            nationality="IN", hpid=hpid,
        )
        self.db.add(profile)
        self.db.flush()
        self.db.add(VesselCrew(
            vessel_id=self.vessel.id, name="Crew", rank="able_seaman",
            hp_id=hpid, shore_pass_eligible=shore_pass_eligible,
        ))
        self.db.flush()
        return profile

    def manifest_only_crew(self, shore_pass_eligible=True):
        """Someone on the crew list who has never registered an account."""
        hpid = _uniq("HP")
        self.db.add(VesselCrew(
            vessel_id=self.vessel.id, name="Unregistered Crew", rank="oiler",
            hp_id=hpid, shore_pass_eligible=shore_pass_eligible,
        ))
        self.db.flush()
        return hpid

    def pass_for(self, crew, out, back):
        self.db.add(ShorePass(
            crew_profile_id=crew.id, shore_pass_id=_uniq("SP"),
            out_time=out, in_time=back,
        ))
        self.db.flush()

    def trip_for(self, crew, started, completed, created=None, passengers=None):
        self.db.add(CabBooking(
            booking_id=_uniq("CAB"), crew_id=crew.id,
            pickup_address="Gate", pickup_lat=0, pickup_lng=0,
            drop_address="City", drop_lat=0, drop_lng=0,
            vehicle_type="ac", vehicle_name="Sedan",
            estimated_price=100, distance_km=5,
            status=BookingStatus.COMPLETED,
            created_at=created or started,
            trip_started_at=started, trip_completed_at=completed,
            crew_member_ids=passengers,
        ))
        self.db.flush()

    def report(self):
        return shore_leave_report(
            vessel_id=self.vessel.id, report_date=REPORT_DATE,
            db=self.db, current_user=self.agent,
        )

    def test_pass_only_crew_are_in_the_average_not_just_the_denominator(self):
        """The defect: cab minutes over a headcount that included pass-only crew.

        One hour in a cab and four hours on a pass average to two and a half
        hours. Dividing the cab hour alone by both people gave 30 minutes.
        """
        rider = self.crew()
        walker = self.crew()
        self.trip_for(rider, started=_at(10), completed=_at(11))
        self.pass_for(walker, out=_at(10), back=_at(14))

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 2)
        self.assertEqual(result.average_duration_minutes, 150)

    def test_a_cab_taken_during_a_pass_is_not_counted_twice(self):
        """A cab ride happens during shore leave; it is not extra time ashore."""
        crew = self.crew()
        self.pass_for(crew, out=_at(9), back=_at(17))
        self.trip_for(crew, started=_at(11), completed=_at(12))

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 1)
        self.assertEqual(result.average_duration_minutes, 480)

    def test_the_worked_example(self):
        """Two cabs of four, out two hours and three.

            trip 1: 4 crew x 2h =  8 crew-hours
            trip 2: 4 crew x 3h = 12 crew-hours
            total  = 20 crew-hours over 8 crew ashore = 2.5h each

        Crew-hours count each passenger's own time, so a shared cab is not one
        person's two hours but four people's.
        """
        first = [self.crew() for _ in range(4)]
        second = [self.crew() for _ in range(4)]
        self.trip_for(first[0], started=_at(9), completed=_at(11),
                      passengers=[c.hpid for c in first[1:]])
        self.trip_for(second[0], started=_at(13), completed=_at(16),
                      passengers=[c.hpid for c in second[1:]])

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 8)
        self.assertEqual(result.average_duration_minutes, 150)

    def test_a_crew_member_on_two_trips_counts_their_whole_time_once(self):
        """The same person out twice is one head, with both stretches summed.

        Their four hours ashore are four hours, not two trips of two averaged
        back down — and the gap they spent aboard between the two is not leave.
        """
        crew = self.crew()
        self.trip_for(crew, started=_at(9), completed=_at(11))
        self.trip_for(crew, started=_at(14), completed=_at(16))

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 1)
        self.assertEqual(result.average_duration_minutes, 240)

    def test_crew_still_ashore_are_left_out_of_the_average(self):
        """The figure is leave per *eligible* head, not per completed trip.

        Someone still ashore has no finished duration to contribute yet, so
        they are left out of both the crew-hours and the head count rather than
        counted as a zero. They are reported separately as `still_ashore`.
        """
        returned = self.crew()
        still_out = self.crew()
        self.pass_for(returned, out=_at(10), back=_at(12))
        self.pass_for(still_out, out=_at(10), back=None)

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 2)
        self.assertEqual(result.still_ashore, 1)
        self.assertEqual(result.average_duration_minutes, 120)

    def test_the_average_does_not_sag_when_most_of_the_ship_stays_aboard(self):
        """One ten-minute ride among six eligible crew is a ten-minute ride.

        Eligibility belongs to utilisation — one of six went, so 17% — not to
        the average, which answers how long a crew member who went ashore was
        actually out.
        """
        rider = self.crew()
        for _ in range(5):
            self.crew()
        self.trip_for(rider, started=_at(10), completed=_at(10, 10))

        result = self.report()

        self.assertEqual(result.eligible_for_shore_leave, 6)
        self.assertEqual(result.crew_went_ashore, 1)
        self.assertEqual(result.shore_leave_utilisation_pct, 17)
        self.assertEqual(result.average_duration_minutes, 10)

    def test_an_unregistered_passenger_still_counts_as_ashore(self):
        """A cab booked for three puts three ashore.

        Passengers used to be resolved through crew *accounts*, so anyone on the
        manifest who had never registered was dropped and a three-person booking
        was reported as one.
        """
        booker = self.crew()
        registered = self.crew()
        unregistered_hpid = self.manifest_only_crew()

        self.trip_for(
            booker, started=_at(10), completed=_at(12),
            passengers=[registered.hpid, unregistered_hpid],
        )

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 3)
        self.assertEqual(result.returned_safely, 3)

    def test_a_passenger_id_that_is_not_on_this_manifest_is_ignored(self):
        """Passenger IDs are typed by hand and validated nowhere."""
        booker = self.crew()

        self.trip_for(
            booker, started=_at(10), completed=_at(12),
            passengers=["HP-SOMEONE-ELSES-SHIP", "", None],
        )

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 1)

    def test_time_back_aboard_between_two_trips_is_not_shore_leave(self):
        """The "12h 21m" defect: gaps between separate trips billed as leave.

        Each person's time ashore was the envelope from first departure to last
        return, so a crew member who took a short cab in the morning and another
        in the evening was reported as having spent the whole day ashore —
        including the hours they were back aboard in between.
        """
        crew = self.crew()
        self.trip_for(crew, started=_at(8), completed=_at(9))
        self.trip_for(crew, started=_at(19), completed=_at(20, 21))

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 1)
        # Two hours and 21 minutes ashore, not the 12h 21m envelope.
        self.assertEqual(result.average_duration_minutes, 141)

    def test_a_completed_trip_without_timestamps_still_counts_as_returned(self):
        """Legacy rows recorded the status but not the times.

        The trip is finished, so the crew member is demonstrably back aboard.
        Inferring "still ashore" from the missing end timestamp stranded them
        ashore permanently and left the day unable to close out.
        """
        crew = self.crew()
        self.db.add(CabBooking(
            booking_id=_uniq("CAB"), crew_id=crew.id,
            pickup_address="Gate", pickup_lat=0, pickup_lng=0,
            drop_address="City", drop_lat=0, drop_lng=0,
            vehicle_type="ac", vehicle_name="Sedan",
            estimated_price=100, distance_km=5,
            status=BookingStatus.COMPLETED,
            created_at=_at(9),
        ))
        self.db.flush()

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 1)
        self.assertEqual(result.returned_safely, 1)
        self.assertEqual(result.still_ashore, 0)
        self.assertTrue(result.all_returned)
        # Back aboard, but with no timestamps there is nothing to measure.
        self.assertIsNone(result.average_duration_minutes)

    def test_a_cab_ashore_and_back_counts_as_returned_without_a_shore_pass(self):
        """Returns used to be read off shore-pass in_time alone.

        Crew who went ashore by cab had no pass to sign back in, so the report
        showed "0 / 1 returned" and "1 still ashore" beside their own completed
        trip.
        """
        crew = self.crew()
        self.trip_for(crew, started=_at(10), completed=_at(12))

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 1)
        self.assertEqual(result.returned_safely, 1)
        self.assertEqual(result.still_ashore, 0)
        self.assertTrue(result.all_returned)

    def test_anyone_who_went_ashore_counts_towards_the_average(self):
        """Eligibility gates utilisation, not time actually spent ashore.

        A crew member the manifest did not mark eligible who nonetheless went
        ashore was really ashore, and their hours are real. Excluding them would
        report an average over people while quietly dropping some of them.
        """
        eligible = self.crew()
        ineligible = self.crew(shore_pass_eligible=False)
        self.pass_for(eligible, out=_at(10), back=_at(12))
        self.pass_for(ineligible, out=_at(9), back=_at(17))

        result = self.report()

        self.assertEqual(result.eligible_for_shore_leave, 1)
        self.assertEqual(result.crew_went_ashore, 2)
        # (120 + 480) / 2
        self.assertEqual(result.average_duration_minutes, 300)


class GroupBookingPassengerTests(ShoreLeaveAverageTests):
    """A shared cab puts everyone in it ashore, not just whoever booked it.

    crew_member_ids holds HeyPorts IDs typed in by the booking crew member. They
    are validated nowhere, so the report resolves them through this vessel's
    manifest and ignores anything that does not land on it.
    """

    def test_fellow_passengers_on_the_manifest_are_counted(self):
        booker = self.crew()
        passenger = self.crew()
        self.trip_for(
            booker, started=_at(10), completed=_at(12),
            passengers=[passenger.hpid],
        )

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 2)
        # Both were in the same cab, so both were ashore for the same two hours.
        self.assertEqual(result.average_duration_minutes, 120)

    def test_an_unrecognised_id_does_not_invent_a_person(self):
        booker = self.crew()
        self.trip_for(
            booker, started=_at(10), completed=_at(12),
            passengers=["HP-typo-nobody", ""],
        )

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 1)

    def test_another_vessels_crew_cannot_be_added_to_this_report(self):
        booker = self.crew()

        other_user = User(
            email=_uniq("other") + "@example.com", hashed_password="x", role="crew"
        )
        self.db.add(other_user)
        self.db.flush()
        stranger = CrewProfile(
            user_id=other_user.id, full_name="Stranger", rank="able_seaman",
            nationality="IN", hpid=_uniq("HP"),
        )
        self.db.add(stranger)
        self.db.flush()

        self.trip_for(
            booker, started=_at(10), completed=_at(12),
            passengers=[stranger.hpid],
        )

        result = self.report()

        self.assertEqual(result.crew_went_ashore, 1)


class TripReportingDayTests(ShoreLeaveAverageTests):
    """A trip belongs to the day it ran, matching a shore pass's out_time."""

    def test_a_trip_booked_before_midnight_counts_on_the_day_it_ran(self):
        """Booked at 23:30 the night before, driven at 00:30 this morning."""
        crew = self.crew()
        self.trip_for(
            crew,
            created=_at(23, 30, day=4),
            started=_at(0, 30), completed=_at(1, 30),
        )

        result = self.report()

        self.assertEqual(result.completed_trips, 1)
        self.assertEqual(result.crew_went_ashore, 1)
        self.assertEqual(result.average_duration_minutes, 60)

    def test_a_trip_that_ran_the_next_day_is_not_on_this_report(self):
        """Booked at 23:30 tonight, driven after midnight — that is tomorrow."""
        crew = self.crew()
        self.trip_for(
            crew,
            created=_at(23, 30),
            started=_at(0, 30, day=6), completed=_at(1, 30, day=6),
        )

        result = self.report()

        self.assertEqual(result.completed_trips, 0)
        self.assertEqual(result.crew_went_ashore, 0)
        self.assertIsNone(result.average_duration_minutes)

    def test_a_booking_that_never_started_puts_nobody_ashore(self):
        """Booked but never driven: nobody has gone ashore on it yet.

        This used to count as a departure, which was wrong twice over. The crew
        member is sitting aboard waiting for a driver, and because the trip
        never runs there is nothing for them to finish — so they were also
        counted as never having returned, and stayed "still ashore" forever.
        """
        crew = self.crew()
        self.db.add(CabBooking(
            booking_id=_uniq("CAB"), crew_id=crew.id,
            pickup_address="Gate", pickup_lat=0, pickup_lng=0,
            drop_address="City", drop_lat=0, drop_lng=0,
            vehicle_type="ac", vehicle_name="Sedan",
            estimated_price=100, distance_km=5,
            status=BookingStatus.PENDING,
            created_at=_at(9),
        ))
        self.db.flush()

        result = self.report()

        self.assertEqual(result.completed_trips, 0)
        self.assertEqual(result.crew_went_ashore, 0)
        self.assertEqual(result.still_ashore, 0)
        self.assertIsNone(result.average_duration_minutes)


if __name__ == "__main__":
    unittest.main()
