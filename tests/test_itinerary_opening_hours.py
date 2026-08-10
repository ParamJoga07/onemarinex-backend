"""Itinerary suggestions must respect when venues are actually open.

Two problems fixed here:

1. DAY_ABBREV was indexed one day out. datetime.weekday() returns 0 for Monday,
   but the map said 0 -> "Sun", so every working-days check compared against the
   wrong day.

2. The opening-hours filter was commented out entirely. The check it called
   asked "is this open right now", which is the wrong question for a shore leave
   running several hours — it would drop a restaurant opening at noon from a
   package starting at 10am. The replacement asks whether the venue is open at
   any point while the crew are ashore.
"""

import unittest
from datetime import datetime

from app.api.v1.routes_itinerary import (
    DAY_ABBREV,
    ItineraryStop,
    schedule_itinerary,
    distance_between_stops,
    vendor_open_during,
)


class DayAbbrevTests(unittest.TestCase):
    def test_weekday_indexes_map_to_the_right_day(self):
        # Python: Monday is 0, Sunday is 6.
        for date, expected in [
            (datetime(2026, 8, 3), "Mon"),
            (datetime(2026, 8, 7), "Fri"),
            (datetime(2026, 8, 8), "Sat"),
            (datetime(2026, 8, 9), "Sun"),
        ]:
            with self.subTest(date=date):
                self.assertEqual(DAY_ABBREV[date.weekday()], expected)


class VendorOpenDuringTests(unittest.TestCase):
    MONDAY_10AM = datetime(2026, 8, 3, 10, 0)

    def test_no_hours_configured_is_always_open(self):
        self.assertTrue(vendor_open_during(None, self.MONDAY_10AM, 4))
        self.assertTrue(vendor_open_during({}, self.MONDAY_10AM, 4))

    def test_venue_opening_later_in_the_window_is_kept(self):
        """The case the old 'is it open now' check got wrong."""
        lunch_only = {"open_time": "12:00", "close_time": "23:00"}

        # 10am start, 4 hours ashore -> crew can be there from noon.
        self.assertTrue(vendor_open_during(lunch_only, self.MONDAY_10AM, 4))

    def test_venue_shut_for_the_whole_window_is_dropped(self):
        night_club = {"open_time": "21:00", "close_time": "23:30"}

        # 10am start, only 3 hours ashore -> back aboard long before it opens.
        self.assertFalse(vendor_open_during(night_club, self.MONDAY_10AM, 3))

    def test_venue_closing_before_the_crew_arrive_is_dropped(self):
        breakfast_only = {"open_time": "06:00", "close_time": "09:00"}

        self.assertFalse(vendor_open_during(breakfast_only, self.MONDAY_10AM, 4))

    def test_closed_today_is_dropped(self):
        weekends_only = {
            "open_time": "09:00", "close_time": "22:00",
            "working_days": "Sat,Sun",
        }

        self.assertFalse(vendor_open_during(weekends_only, self.MONDAY_10AM, 6))

    def test_open_today_is_kept(self):
        weekdays = {
            "open_time": "09:00", "close_time": "22:00",
            "working_days": "Mon,Tue,Wed,Thu,Fri",
        }

        self.assertTrue(vendor_open_during(weekdays, self.MONDAY_10AM, 6))

    def test_working_days_check_uses_the_correct_day(self):
        """Guards the off-by-one directly: Monday must not read as Sunday."""
        monday_only = {"open_time": "00:00", "close_time": "23:59", "working_days": "Mon"}
        sunday_only = {"open_time": "00:00", "close_time": "23:59", "working_days": "Sun"}

        self.assertTrue(vendor_open_during(monday_only, self.MONDAY_10AM, 2))
        self.assertFalse(vendor_open_during(sunday_only, self.MONDAY_10AM, 2))

    def test_overnight_venue_spanning_midnight(self):
        late_bar = {"open_time": "22:00", "close_time": "02:00"}
        evening = datetime(2026, 8, 3, 21, 0)

        # Ashore 21:00-01:00 overlaps the 22:00 opening.
        self.assertTrue(vendor_open_during(late_bar, evening, 4))
        # Ashore 10:00-14:00 does not.
        self.assertFalse(vendor_open_during(late_bar, self.MONDAY_10AM, 4))

    def test_long_shore_leave_reaches_the_next_day(self):
        tuesday_only = {"open_time": "09:00", "close_time": "17:00", "working_days": "Tue"}

        # A 30-hour window from Monday 10am runs into Tuesday.
        self.assertTrue(vendor_open_during(tuesday_only, self.MONDAY_10AM, 30))


class ItinerarySchedulingTests(unittest.TestCase):
    def stop(self, **overrides):
        values = dict(
            vendor_id=1, name="Lunch", category="restaurant", tags=["food"],
            avg_time_hours=1, distance_from_port=10, rating=4.5,
            open_time="12:00", close_time="14:00", working_days=["Mon"],
        )
        values.update(overrides)
        return ItineraryStop(**values)

    def test_arrival_waits_for_opening_and_departure_stays_inside_hours(self):
        result = schedule_itinerary(
            [self.stop()], datetime(2026, 8, 3, 10, 0), 4, 60, 3,
        )

        self.assertIsNotNone(result)
        stops, elapsed = result
        self.assertEqual(stops[0].scheduled_arrival, "2026-08-03T12:00:00")
        self.assertEqual(stops[0].scheduled_departure, "2026-08-03T13:00:00")
        self.assertEqual(elapsed, 190)

    def test_stop_is_rejected_when_full_visit_cannot_finish_before_close(self):
        result = schedule_itinerary(
            [self.stop(open_time="10:00", close_time="11:00", avg_time_hours=1)],
            datetime(2026, 8, 3, 10, 30), 4, 60, 3,
        )

        self.assertIsNone(result)

    def test_overnight_opening_window_is_supported(self):
        result = schedule_itinerary(
            [self.stop(open_time="22:00", close_time="02:00", working_days=["Mon"], distance_from_port=1)],
            datetime(2026, 8, 3, 21, 30), 4, 60, 3,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result[0][0].scheduled_arrival, "2026-08-03T22:00:00")

    def test_shared_placeholder_coordinates_use_distance_hints(self):
        first = self.stop(distance_from_port=2, lat=17.7, lng=83.3)
        second = self.stop(vendor_id=2, distance_from_port=8, lat=17.7, lng=83.3)

        self.assertEqual(distance_between_stops(first, second, 3), 9)


if __name__ == "__main__":
    unittest.main()
