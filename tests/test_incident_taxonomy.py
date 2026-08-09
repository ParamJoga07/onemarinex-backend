"""The incident taxonomy is the contract between crew, agents and reports.

Six categories, cut from a proposed nine at the customer's request. These tests
pin the things that would quietly break reporting if they drifted: the stored
values, the safety-critical default severity, and sub-category ownership.
"""

import unittest

from app.services import incident_taxonomy as tax


class CategoryShapeTests(unittest.TestCase):
    def test_there_are_exactly_six_categories(self):
        self.assertEqual(len(tax.INCIDENT_CATEGORIES), 6)

    def test_stored_values_are_stable(self):
        """Labels may be reworded; these values are what lands in the database."""
        self.assertEqual(tax.category_values(), [
            "medical_emergency",
            "safety_security",
            "driver_vehicle",
            "service_complaint",
            "payment_issue",
            "general_support",
        ])

    def test_every_category_has_sub_categories_and_a_severity(self):
        for cat in tax.INCIDENT_CATEGORIES:
            with self.subTest(cat["value"]):
                self.assertTrue(cat["sub_categories"], "no sub-categories")
                self.assertIn(cat["severity"], tax.SEVERITIES)

    def test_values_are_unique_across_and_within_categories(self):
        self.assertEqual(len(set(tax.category_values())), 6)
        for cat in tax.INCIDENT_CATEGORIES:
            subs = [s["value"] for s in cat["sub_categories"]]
            self.assertEqual(len(subs), len(set(subs)), cat["value"])

    def test_nothing_is_unreportable(self):
        """General Support exists so crew are never blocked by a missing option."""
        general = [c for c in tax.INCIDENT_CATEGORIES if c["value"] == "general_support"][0]
        self.assertIn("other", [s["value"] for s in general["sub_categories"]])

    def test_lost_property_survived_the_cut_to_six(self):
        """It lost its own category but must still be reportable."""
        general = [c for c in tax.INCIDENT_CATEGORIES if c["value"] == "general_support"][0]
        self.assertIn("lost_property", [s["value"] for s in general["sub_categories"]])

    def test_vehicle_faults_are_reportable_without_blaming_the_driver(self):
        driver = [c for c in tax.INCIDENT_CATEGORIES if c["value"] == "driver_vehicle"][0]
        subs = [s["value"] for s in driver["sub_categories"]]
        self.assertIn("vehicle_breakdown", subs)
        self.assertIn("unsafe_vehicle", subs)


class SeverityTests(unittest.TestCase):
    def test_safety_critical_categories_default_to_high(self):
        for value in ("medical_emergency", "safety_security"):
            with self.subTest(value):
                self.assertEqual(tax.default_severity_for(value), "high")

    def test_routine_categories_do_not_default_to_high(self):
        for value in ("service_complaint", "payment_issue", "general_support"):
            with self.subTest(value):
                self.assertNotEqual(tax.default_severity_for(value), "high")

    def test_unknown_category_falls_back_to_the_middle(self):
        self.assertEqual(tax.default_severity_for("nonsense"), tax.DEFAULT_SEVERITY)
        self.assertEqual(tax.default_severity_for(None), tax.DEFAULT_SEVERITY)


class ValidationTests(unittest.TestCase):
    def test_category_validation(self):
        self.assertTrue(tax.is_valid_category("payment_issue"))
        self.assertFalse(tax.is_valid_category("lost_property"))  # now a sub-category
        self.assertFalse(tax.is_valid_category(None))

    def test_sub_category_must_belong_to_its_category(self):
        self.assertTrue(tax.is_valid_sub_category("payment_issue", "overcharged"))
        self.assertFalse(tax.is_valid_sub_category("payment_issue", "harassment"))

    def test_sub_category_is_optional(self):
        self.assertTrue(tax.is_valid_sub_category("payment_issue", None))
        self.assertTrue(tax.is_valid_sub_category("payment_issue", ""))

    def test_sub_category_without_a_valid_category_is_rejected(self):
        self.assertFalse(tax.is_valid_sub_category("nonsense", "overcharged"))


class LabelTests(unittest.TestCase):
    def test_labels_resolve(self):
        self.assertEqual(tax.category_label("driver_vehicle"), "Driver & Vehicle")
        self.assertEqual(
            tax.sub_category_label("general_support", "lost_property"), "Lost property"
        )

    def test_unknown_values_are_shown_rather_than_hidden(self):
        self.assertEqual(tax.category_label("legacy_value"), "legacy_value")
        self.assertEqual(tax.sub_category_label("general_support", "odd"), "odd")


if __name__ == "__main__":
    unittest.main()
