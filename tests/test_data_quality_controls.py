import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.port import Port
from app.services.crew_reference import normalize_nationality, normalize_rank
from app.services.crew_service import ensure_stable_hpid
from app.services.port_identity import canonical_port_code, canonical_port_key, matching_port_values, reconcile_port_identities
from app.services.vendor_data import (
    normalize_vendor_information,
    repair_legacy_vendor_information,
    validate_coordinates,
)


class CrewIdentityTests(unittest.TestCase):
    def test_existing_hpid_is_never_regenerated(self):
        profile = SimpleNamespace(
            id=7, user_id=11, hpid="HP-ORIGINAL", passport_number="NEW-PASSPORT",
            nationality="PH", current_port="port_new",
        )
        db = MagicMock()

        self.assertEqual(ensure_stable_hpid(db, profile), "HP-ORIGINAL")
        db.query.assert_not_called()

    def test_nationality_is_iso_alpha_two(self):
        for raw in ("India", "INDIAN", "in"):
            self.assertEqual(normalize_nationality(raw, strict=True), "IN")
        with self.assertRaises(ValueError):
            normalize_nationality("Atlantis", strict=True)

    def test_historical_rank_aliases_normalize(self):
        self.assertEqual(normalize_rank("2 ENG"), "second_engineer")
        self.assertEqual(normalize_rank("ORDINARY SEAMAN"), "ordinary_seaman")
        self.assertEqual(normalize_rank("Custom Specialist"), "custom_specialist")


class VendorDataTests(unittest.TestCase):
    def test_hours_are_stored_structurally(self):
        result = normalize_vendor_information({
            "open_time": "09:00", "close_time": "18:30",
            "working_days": "Mon, Wed,Mon",
        })
        self.assertEqual(result["working_days"], ["Mon", "Wed"])

    def test_malformed_range_in_open_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "HH:MM"):
            normalize_vendor_information({"open_time": "09:00-18:00", "close_time": "18:00"})

    def test_unambiguous_legacy_range_can_be_repaired_offline(self):
        result = repair_legacy_vendor_information({"timings": "16:00-01:00"})
        self.assertEqual(result["open_time"], "16:00")
        self.assertEqual(result["close_time"], "01:00")
        self.assertEqual(
            result["working_days"],
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        )

    def test_missing_legacy_hours_are_not_invented(self):
        self.assertIsNone(
            repair_legacy_vendor_information({"timings": "Call venue"})
        )

    def test_placeholder_and_out_of_range_coordinates_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_coordinates(0, 0)
        with self.assertRaises(ValueError):
            validate_coordinates(91, 20)
        validate_coordinates(17.7019, 83.2897)


class PortIdentityTests(unittest.TestCase):
    def test_short_and_long_visakhapatnam_names_share_a_key(self):
        self.assertEqual(
            canonical_port_key("port_port_of_visakhapatnam"),
            canonical_port_key("Visakhapatnam Port"),
        )

    def test_canonical_code_never_repeats_port_prefix(self):
        self.assertEqual(canonical_port_code("port_port_of_visakhapatnam"), "port_visakhapatnam")

    def test_alias_values_include_every_matching_record(self):
        ports = [
            SimpleNamespace(name="Port of Visakhapatnam", code="port_port_of_visakhapatnam"),
            SimpleNamespace(name="Visakhapatnam Port", code="port_visakhapatnam"),
            SimpleNamespace(name="Port of Chennai", code="port_chennai"),
        ]
        values = matching_port_values(ports, "Visakhapatnam")
        self.assertIn("port_visakhapatnam", values)
        self.assertIn("port_port_of_visakhapatnam", values)
        self.assertNotIn("port_chennai", values)

    def test_port_model_generates_and_enforces_canonical_identity(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            first = Port(name="Port of Visakhapatnam", code="port_visakhapatnam")
            db.add(first)
            db.commit()
            self.assertEqual(first.canonical_key, "visakhapatnam")

            db.add(Port(name="Visakhapatnam Port", code="visakhapatnam_port"))
            with self.assertRaises(IntegrityError):
                db.commit()
        finally:
            db.rollback()
            db.close()

    def test_reconciliation_repoints_dependents_and_creates_active_rule(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE ports (id INTEGER PRIMARY KEY, name VARCHAR, code VARCHAR, canonical_key VARCHAR, is_active BOOLEAN)")
            connection.exec_driver_sql("CREATE TABLE agent_profiles (id INTEGER PRIMARY KEY, assigned_port VARCHAR)")
            connection.exec_driver_sql("CREATE TABLE crew_profiles (id INTEGER PRIMARY KEY, current_port VARCHAR)")
            connection.exec_driver_sql("CREATE TABLE port_rules (id INTEGER PRIMARY KEY, port_name VARCHAR UNIQUE, rules JSON, timezone VARCHAR, advance_booking_buffer_minutes INTEGER)")
            connection.exec_driver_sql("CREATE TABLE port_configs (id INTEGER PRIMARY KEY, port_name VARCHAR UNIQUE, shore_leave_end VARCHAR, flexible_enabled BOOLEAN, guaranteed_enabled BOOLEAN)")
            connection.exec_driver_sql("INSERT INTO ports VALUES (1, 'Port of Visakhapatnam', 'port_port_of_visakhapatnam', 'visakhapatnam', 1)")
            connection.exec_driver_sql("INSERT INTO agent_profiles VALUES (1, 'port_visakhapatnam')")
            connection.exec_driver_sql("INSERT INTO crew_profiles VALUES (1, 'Port of Visakhapatnam')")
            connection.exec_driver_sql("INSERT INTO port_rules VALUES (1, 'port_dubai', '[]', 'Asia/Dubai', 30)")
            connection.exec_driver_sql("INSERT INTO port_configs VALUES (1, 'Visakhapatnam', '17:00', 1, 1)")
            connection.exec_driver_sql("INSERT INTO port_configs VALUES (2, 'Port of Visakhapatnam', '17:00', 1, 1)")

            result = reconcile_port_identities(connection)
            self.assertEqual(result["rules_created"], 1)
            self.assertEqual(result["orphan_rules_removed"], 1)
            self.assertEqual(connection.exec_driver_sql("SELECT code FROM ports").scalar_one(), "port_visakhapatnam")
            self.assertEqual(connection.exec_driver_sql("SELECT current_port FROM crew_profiles").scalar_one(), "port_visakhapatnam")
            self.assertEqual(connection.exec_driver_sql("SELECT port_name FROM port_rules").scalar_one(), "port_visakhapatnam")
            self.assertIn("Return before shore leave ends", connection.exec_driver_sql("SELECT rules FROM port_rules").scalar_one())
            self.assertEqual(connection.exec_driver_sql("SELECT port_name FROM port_configs").scalar_one(), "port_visakhapatnam")


if __name__ == "__main__":
    unittest.main()
