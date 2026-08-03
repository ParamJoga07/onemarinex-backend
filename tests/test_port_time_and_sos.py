from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.api.v1 import routes_crew
from app.services.port_time import (
    port_clock_snapshot,
    port_closed_reason,
    port_closing_buffer_reason,
)


class PortTimeTests(unittest.TestCase):
    def test_port_clock_uses_port_timezone_from_server_utc(self):
        now = datetime(2026, 8, 2, 1, 30, tzinfo=timezone.utc)

        india = port_clock_snapshot("port_visakhapatnam", now_utc=now)
        dubai = port_clock_snapshot("Dubai Port", now_utc=now)

        self.assertEqual(india["timezone"], "Asia/Kolkata")
        self.assertEqual(india["port_time"], "07:00")
        self.assertEqual(dubai["timezone"], "Asia/Dubai")
        self.assertEqual(dubai["port_time"], "05:30")

    def test_pickup_before_opening_is_closed_and_opening_is_allowed(self):
        zone = ZoneInfo("Asia/Kolkata")

        self.assertIsNotNone(
            port_closed_reason(
                datetime(2026, 8, 3, 7, 59, tzinfo=zone),
                "08:00",
                "18:00",
                ["Mon"],
            )
        )
        self.assertIsNone(
            port_closed_reason(
                datetime(2026, 8, 3, 8, 0, tzinfo=zone),
                "08:00",
                "18:00",
                ["Mon"],
            )
        )

    def test_overnight_port_window(self):
        zone = ZoneInfo("Asia/Dubai")

        self.assertIsNone(
            port_closed_reason(
                datetime(2026, 8, 3, 1, 0, tzinfo=zone),
                "22:00",
                "02:00",
                None,
            )
        )
        self.assertIsNotNone(
            port_closed_reason(
                datetime(2026, 8, 3, 3, 0, tzinfo=zone),
                "22:00",
                "02:00",
                None,
            )
        )

    def test_malformed_config_fails_closed(self):
        result = port_closed_reason(
            datetime(2026, 8, 3, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
            "not-a-time",
            "18:00",
            None,
        )

        self.assertIn("temporarily unavailable", result or "")

    def test_package_cutoff_starts_exactly_two_hours_before_closing(self):
        zone = ZoneInfo("Asia/Kolkata")

        self.assertIsNone(
            port_closing_buffer_reason(
                datetime(2026, 8, 3, 15, 59, tzinfo=zone),
                "08:00",
                "18:00",
                120,
            )
        )
        result = port_closing_buffer_reason(
            datetime(2026, 8, 3, 16, 0, tzinfo=zone),
            "08:00",
            "18:00",
            120,
        )

        self.assertIn("final 2 hours", result or "")

    def test_package_cutoff_supports_overnight_port_hours(self):
        zone = ZoneInfo("Asia/Dubai")

        self.assertIsNone(
            port_closing_buffer_reason(
                datetime(2026, 8, 3, 22, 59, tzinfo=zone),
                "22:00",
                "01:00",
                120,
            )
        )
        self.assertIsNotNone(
            port_closing_buffer_reason(
                datetime(2026, 8, 3, 23, 0, tzinfo=zone),
                "22:00",
                "01:00",
                120,
            )
        )


class PickupAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.zone = ZoneInfo("Asia/Kolkata")
        self.port_now = datetime(2026, 8, 3, 7, 30, tzinfo=self.zone)
        self.clock = {
            "timezone": "Asia/Kolkata",
            "zone": self.zone,
            "server_time": self.port_now.astimezone(timezone.utc),
            "port_now": self.port_now,
            "port_date": "2026-08-03",
            "port_time": "07:30",
            "port_day": "Mon",
        }
        self.rule = SimpleNamespace(
            timezone="Asia/Kolkata",
            opening_time="08:00",
            closing_time="18:00",
            working_days=["Mon"],
            advance_booking_buffer_minutes=30,
        )

    def availability(self, scheduled_time, trip_type):
        with (
            patch.object(routes_crew, "_port_rule_for", return_value=self.rule),
            patch.object(routes_crew, "port_clock_snapshot", return_value=self.clock),
        ):
            return routes_crew._pickup_availability(
                object(), "port_visakhapatnam", scheduled_time, trip_type
            )

    def test_coordinated_pickup_uses_selected_port_wall_time(self):
        before_open = self.availability(
            datetime(2026, 8, 3, 7, 59), "coordinated_transfer"
        )
        at_open = self.availability(
            datetime(2026, 8, 3, 8, 0), "coordinated_transfer"
        )

        self.assertFalse(before_open["available"])
        self.assertTrue(at_open["available"])

    def test_package_ignores_crafted_future_client_time(self):
        result = self.availability(
            datetime(2026, 8, 3, 12, 0), "package_trip"
        )

        self.assertFalse(result["available"])
        self.assertEqual(result["pickup_at"], self.port_now)

    def test_package_uses_server_port_time_for_closing_cutoff(self):
        self.port_now = datetime(2026, 8, 3, 16, 0, tzinfo=self.zone)
        self.clock.update(
            server_time=self.port_now.astimezone(timezone.utc),
            port_now=self.port_now,
            port_time="16:00",
        )

        result = self.availability(
            datetime(2026, 8, 3, 9, 0),
            "package_trip",
        )

        self.assertFalse(result["available"])
        self.assertIn("final 2 hours", result["reason"] or "")
        self.assertEqual(result["pickup_at"], self.port_now)

    def test_availability_uses_authenticated_profile_port(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
            current_port="trusted_profile_port"
        )
        current_user = SimpleNamespace(id=42, role="crew")

        with patch.object(
            routes_crew,
            "_pickup_availability",
            return_value={"available": True},
        ) as availability:
            routes_crew.get_pickup_availability(
                port="client_tampered_port",
                scheduled_time=None,
                trip_type="package_trip",
                db=db,
                current_user=current_user,
            )

        self.assertEqual(availability.call_args.args[1], "trusted_profile_port")


class SosPayloadTests(unittest.TestCase):
    def test_trip_and_location_are_mandatory(self):
        with self.assertRaises(ValidationError):
            routes_crew.SOSTriggerIn.model_validate({"lat": 10, "lng": 20})
        with self.assertRaises(ValidationError):
            routes_crew.SOSTriggerIn.model_validate(
                {"trip_id": "HP-123", "lat": 91, "lng": 20}
            )

        payload = routes_crew.SOSTriggerIn.model_validate(
            {"trip_id": "HP-123", "lat": 17.68, "lng": 83.21}
        )
        self.assertEqual(payload.trip_id, "HP-123")


if __name__ == "__main__":
    unittest.main()
