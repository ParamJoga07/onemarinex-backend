"""A report describes the trip as it was, not as it is now.

Two defects, one cause. `booking_context` read live trip state, so:

- an incident filed after the cab finished still advertised a stop the crew had
  skipped as where they were heading next, when the answer is that the trip was
  over and they had gone back to the ship;
- an SOS raised after the first stop read back as "Trip End (Port)", because by
  the time anyone opened the report the cab had reached the port.

Both are answered by resolving the stops as of the moment the record was made.
"""

from datetime import datetime, timedelta, timezone
import unittest

from app.services.operations_context import booking_context


class _Booking:
    """Only the attributes booking_context reads."""

    def __init__(self, completed_at=None, status="on_trip"):
        self.id = 1
        self.booking_id = "CAB-TEST"
        self.status = status
        self.ride_type = None
        self.pickup_address = "Port Gate"
        self.drop_address = "City"
        self.driver_name = "Driver"
        self.driver_phone = "123"
        self.driver_plate = "AP01"
        self.aggregator_name = "Provider"
        self.provider = None
        self.aggregator = None
        self.assigned_driver = None
        self.created_at = None
        self.trip_started_at = None
        self.started_at = None
        self.trip_completed_at = completed_at
        self.completed_at = None


START = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)


def _stop(name, reached, minutes=None, stop_type="explore_places"):
    return {
        "id": name.lower().replace(" ", "_"),
        "name": name,
        "address": name,
        "type": stop_type,
        "reached": reached,
        "reached_at": (START + timedelta(minutes=minutes)).isoformat() if minutes else None,
    }


class TripStopsAsOfTests(unittest.TestCase):
    def _context(self, booking, stops, as_of=None):
        """Drive booking_context with a fixed itinerary.

        The stops normally arrive through a driver magic link; patching the
        serializer keeps this about the resolution logic rather than the
        plumbing that fetches them.
        """
        from unittest.mock import patch

        class _Query:
            def filter(self, *a, **k): return self
            def order_by(self, *a, **k): return self
            def first(self): return object()

        class _Db:
            def query(self, *a, **k): return _Query()

        with patch(
            "app.services.operations_context.serialize_magic_link_public_payload",
            return_value={"itinerary": stops},
        ):
            return booking_context(_Db(), booking, as_of=as_of)

    # --- the completed trip with a skipped stop ----------------------------

    def test_a_skipped_stop_is_not_the_next_destination_once_the_trip_ends(self):
        finished = START + timedelta(hours=4)
        booking = _Booking(completed_at=finished, status="completed")
        stops = [
            _stop("Beach", True, 30),
            _stop("Museum", True, 90),
            _stop("Market", True, 150),
            _stop("Vizag Hair Company", False),
            _stop("Trip End (Port)", True, 230, stop_type="trip_end"),
        ]

        context = self._context(booking, stops, as_of=finished + timedelta(minutes=5))

        self.assertIsNone(context["next_destination"])
        self.assertEqual(context["last_reached_point"]["name"], "Trip End (Port)")

    # --- the SOS raised mid-trip -------------------------------------------

    def test_an_sos_reports_where_the_crew_were_when_it_was_raised(self):
        finished = START + timedelta(hours=4)
        booking = _Booking(completed_at=finished, status="completed")
        stops = [
            _stop("Beach", True, 30),
            _stop("Museum", True, 90),
            _stop("Trip End (Port)", True, 230, stop_type="trip_end"),
        ]
        raised = START + timedelta(minutes=45)  # after the first stop

        context = self._context(booking, stops, as_of=raised)

        self.assertEqual(context["last_reached_point"]["name"], "Beach")
        self.assertEqual(context["next_destination"]["name"], "Museum")

    def test_without_a_moment_the_trip_is_described_as_it_is_now(self):
        booking = _Booking(status="on_trip")
        stops = [_stop("Beach", True, 30), _stop("Museum", False)]

        context = self._context(booking, stops)

        self.assertEqual(context["last_reached_point"]["name"], "Beach")
        self.assertEqual(context["next_destination"]["name"], "Museum")

    def test_stops_reached_without_a_timestamp_keep_itinerary_order(self):
        """Sorting these as strings put the blank ones first by accident."""
        booking = _Booking(status="on_trip")
        stops = [_stop("Beach", True), _stop("Museum", True), _stop("Market", False)]

        context = self._context(booking, stops)

        self.assertEqual(context["last_reached_point"]["name"], "Museum")

    def test_a_trip_still_running_keeps_its_next_destination(self):
        booking = _Booking(status="on_trip")
        stops = [_stop("Beach", True, 30), _stop("Museum", False)]

        context = self._context(booking, stops, as_of=START + timedelta(minutes=40))

        self.assertEqual(context["next_destination"]["name"], "Museum")


if __name__ == "__main__":
    unittest.main()
