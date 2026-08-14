from decimal import Decimal
from types import SimpleNamespace
import unittest

from pydantic import ValidationError
from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

from app.api.v1.routes_facilities import FacilityOut
from app.api.v1.routes_pubs import PubOut
from app.api.v1.routes_restaurants import get_restaurants
from app.api.v1.routes_superadmin import (
    VendorCreate,
    VendorUpdate,
    create_place,
    get_vendors,
    update_place,
)
from app.db.models.port import Port
from app.db.models.vendors import Vendors
from app.services.vendor_ranking import (
    apply_vendor_commission_ranking,
    categories_for_vendor_section,
)


class VendorCommissionSchemaTests(unittest.TestCase):
    def test_commission_defaults_to_zero_and_stays_within_percentage_bounds(self):
        payload = {
            "name": "Harbour Pub",
            "category": "pub",
            "location_name": "Port Road",
            "distance_from_port": 1.2,
            "lat": 17.7,
            "lng": 83.3,
        }
        self.assertEqual(VendorCreate.model_validate(payload).commission_percentage, 0)
        self.assertEqual(
            VendorUpdate.model_validate({"commission_percentage": 12.5}).commission_percentage,
            12.5,
        )
        with self.assertRaises(ValidationError):
            VendorUpdate.model_validate({"commission_percentage": 100.01})
        with self.assertRaises(ValidationError):
            VendorUpdate.model_validate({"commission_percentage": -0.01})

    def test_commission_is_not_part_of_crew_response_schemas(self):
        self.assertNotIn("commission_percentage", PubOut.model_fields)
        self.assertNotIn("commission_percentage", FacilityOut.model_fields)

    def test_combined_crew_sections_include_both_database_categories(self):
        self.assertEqual(
            categories_for_vendor_section("massage-wellness"),
            ("massage", "wellness"),
        )
        self.assertEqual(
            categories_for_vendor_section("shopping"),
            ("shopping", "utility"),
        )


class VendorCommissionRankingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Port.__table__.create(self.engine)
        Vendors.__table__.create(self.engine)
        self.db = Session(self.engine)
        port = Port(name="Test Port", code="test_port")
        self.db.add(port)
        self.db.flush()
        self.port_id = port.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_vendor(self, name: str, commission: str, rating: float) -> Vendors:
        vendor = Vendors(
            port_id=self.port_id,
            name=name,
            location_name=f"{name} Road",
            distance_from_port=1,
            rating=rating,
            lat=17.7,
            lng=83.3,
            phone="9999999999",
            email=f"{name.lower()}@example.com",
            status="Active",
            category="pub",
            commission_percentage=Decimal(commission),
        )
        self.db.add(vendor)
        return vendor

    def test_highest_commission_ranks_first_then_rating_breaks_ties(self):
        self.add_vendor("Low", "5.00", 5.0)
        self.add_vendor("High Low Rating", "12.50", 3.0)
        self.add_vendor("High High Rating", "12.50", 4.8)
        self.db.commit()

        query = self.db.query(Vendors).filter(
            Vendors.port_id == self.port_id,
            func.lower(Vendors.category) == "pub",
        )
        ranked = apply_vendor_commission_ranking(query).all()

        self.assertEqual(
            [vendor.name for vendor in ranked],
            ["High High Rating", "High Low Rating", "Low"],
        )

        crew_results = get_restaurants(port_id=self.port_id, db=self.db)
        self.assertEqual(crew_results, [])

    def test_superadmin_can_update_commission(self):
        vendor = self.add_vendor("Editable", "1.00", 4.0)
        self.db.commit()

        updated = update_place(
            vendor_id=vendor.id,
            payload=VendorUpdate(commission_percentage=17.25),
            db=self.db,
            current_user=SimpleNamespace(role="superadmin"),
        )

        self.assertEqual(updated.commission_percentage, Decimal("17.25"))

    def test_crew_restaurant_results_are_ranked_without_commission_value(self):
        high = self.add_vendor("High", "15.00", 4.0)
        low = self.add_vendor("Low", "2.00", 5.0)
        high.category = "restaurant"
        low.category = "restaurant"
        self.db.commit()

        results = get_restaurants(port_id=self.port_id, db=self.db)

        self.assertEqual([result["name"] for result in results], ["High", "Low"])
        self.assertTrue(all("commission_percentage" not in result for result in results))

    def test_working_days_round_trip_for_one_several_and_all_days(self):
        """Superadmin create/edit/read uses one canonical weekday contract."""

        admin = SimpleNamespace(role="superadmin")
        all_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        cases = (
            ("One Day", ["Mon"], "Mon", ["Mon"]),
            ("Several Days", "Tue, Thu, Sat", ["Tue", "Thu", "Sat"], ["Tue", "Thu", "Sat"]),
            ("All Days", "All Days", all_days, all_days),
        )

        for suffix, create_days, edit_days, expected in cases:
            created = create_place(
                payload=VendorCreate(
                    name=f"Working Days {suffix}",
                    category="pub",
                    location_name="Port Road",
                    distance_from_port=1,
                    rating=0,
                    lat=17.7,
                    lng=83.3,
                    port_id=self.port_id,
                    phone="9999999999",
                    email=f"{suffix.lower().replace(' ', '-')}@example.com",
                    other_information={
                        "open_time": "09:00",
                        "close_time": "18:00",
                        "working_days": create_days,
                    },
                ),
                db=self.db,
                current_user=admin,
            )
            self.assertEqual(created.other_information["working_days"], expected)
            read_created = get_vendors(
                vendor_id=created.id,
                db=self.db,
                current_user=admin,
            )
            self.assertEqual(read_created[0].other_information["working_days"], expected)

            updated = update_place(
                vendor_id=created.id,
                payload=VendorUpdate(other_information={
                    "open_time": "10:00",
                    "close_time": "19:00",
                    "working_days": edit_days,
                }),
                db=self.db,
                current_user=admin,
            )
            self.assertEqual(updated.other_information["working_days"], expected)
            read_updated = get_vendors(
                vendor_id=created.id,
                db=self.db,
                current_user=admin,
            )
            self.assertEqual(read_updated[0].other_information["working_days"], expected)


if __name__ == "__main__":
    unittest.main()
