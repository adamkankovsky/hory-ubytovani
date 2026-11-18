from __future__ import annotations

import unittest

from hory import analysis


def make_property(
    *,
    platform: str,
    listing_id: str,
    name: str,
    property_type: str,
    max_occupancy: int | None,
    lat: float | None = 47.39,
    lng: float | None = 13.68,
    total: float | None = 1000.0,
    currency: str = "EUR",
) -> dict:
    prop = {
        "id": f"stays_{platform}_{listing_id}",
        "platform": platform,
        "platformListingId": listing_id,
        "url": f"https://example.test/{platform}/{listing_id}",
        "name": name,
        "propertyType": property_type,
        "location": {"lat": lat, "lng": lng, "country": "AT", "city": "Schladming"},
        "maxOccupancy": max_occupancy,
        "bedrooms": 3,
        "bathrooms": 1,
        "amenities": ["parking_free", "crib"],
        "images": ["https://example.test/a.jpg"],
        "host": {"name": "Host"},
    }
    if total is not None:
        prop["price"] = {
            "currency": currency,
            "nightlyPrice": total / 4,
            "totalPrice": total,
            "nights": 4,
        }
    return prop


class ScopeTests(unittest.TestCase):
    def test_house_is_whole_property(self) -> None:
        result = analysis.classify_scope(
            {"name": "Chalet Alpenblick", "propertyType": "house", "maxOccupancy": 15},
            15,
        )
        self.assertEqual(result["scope"], "whole_property")
        self.assertNotIn("capacity_below_group", result["flags"])

    def test_plural_apartment_name_is_ambiguous(self) -> None:
        result = analysis.classify_scope(
            {"name": "Apartments Alpenblick", "propertyType": "apartment", "maxOccupancy": 4},
            15,
        )
        self.assertEqual(result["scope"], "unknown")
        self.assertIn("building_name_without_unit_number", result["flags"])
        self.assertIn("capacity_below_group", result["flags"])

    def test_numbered_apartment_is_unit(self) -> None:
        result = analysis.classify_scope(
            {"name": "Apartment Alpenblick 3", "propertyType": "apartment", "maxOccupancy": 4},
            4,
        )
        self.assertEqual(result["scope"], "single_unit")

    def test_unknown_capacity(self) -> None:
        result = analysis.classify_scope(
            {"name": "Alpenblick", "propertyType": "apartment", "maxOccupancy": None},
            15,
        )
        self.assertIn("capacity_unknown", result["flags"])


class CollectionTests(unittest.TestCase):
    def test_primary_observation_and_multi_room_flag(self) -> None:
        whole = make_property(
            platform="booking",
            listing_id="house1",
            name="Chalet Alpenblick",
            property_type="house",
            max_occupancy=15,
            total=2000,
        )
        suspicious = make_property(
            platform="booking",
            listing_id="apartments1",
            name="Apartments Alpenblick",
            property_type="apartment",
            max_occupancy=4,
            total=900,
        )
        searches = [
            {
                "spec": {
                    "key": "whole",
                    "label": "celá skupina",
                    "adults": 12,
                    "children": 3,
                    "child_ages": [6, 9, 12],
                },
                "envelope": {"data": [whole, suspicious], "meta": {}},
            },
            {
                "spec": {
                    "key": "sub_4a_0c",
                    "label": "menší: 4A",
                    "adults": 4,
                    "children": 0,
                    "child_ages": [],
                },
                "envelope": {
                    "data": [
                        make_property(
                            platform="booking",
                            listing_id="house1",
                            name="Chalet Alpenblick",
                            property_type="house",
                            max_occupancy=15,
                            total=800,
                        )
                    ],
                    "meta": {},
                },
            },
        ]
        properties = analysis.collect_properties(
            searches,
            group_total=15,
            center={"lat": 47.39, "lng": 13.68},
            radius_km=20,
        )
        by_key = {prop["key"]: prop for prop in properties}
        house = by_key["booking:house1"]
        self.assertEqual(house["primary_search"], "whole")
        self.assertTrue(house["capacity_ok"])
        self.assertEqual(len(house["observations"]), 2)

        apartments = by_key["booking:apartments1"]
        self.assertIn("capacity_below_group", apartments["flags"])
        self.assertIn("search_price_may_be_multi_room", apartments["flags"])
        self.assertFalse(apartments["capacity_ok"])

    def test_out_of_radius_is_kept_but_marked(self) -> None:
        prop = make_property(
            platform="airbnb",
            listing_id="far1",
            name="Chalet Far",
            property_type="house",
            max_occupancy=15,
            lat=48.5,
            lng=14.5,
        )
        properties = analysis.collect_properties(
            [
                {
                    "spec": {"key": "whole", "label": "celá skupina", "adults": 12, "children": 3},
                    "envelope": {"data": [prop], "meta": {}},
                }
            ],
            group_total=15,
            center={"lat": 47.39, "lng": 13.68},
            radius_km=20,
        )
        self.assertEqual(len(properties), 1)
        self.assertFalse(properties[0]["in_radius"])


class ClusterTests(unittest.TestCase):
    def test_cross_platform_duplicate_and_same_platform_units(self) -> None:
        props = [
            make_property(
                platform="booking",
                listing_id="alpen1",
                name="Chalet Alpenblick",
                property_type="house",
                max_occupancy=15,
                lat=47.39,
                lng=13.68,
            ),
            make_property(
                platform="airbnb",
                listing_id="123",
                name="Chalet Alpenblick",
                property_type="house",
                max_occupancy=15,
                lat=47.39005,
                lng=13.68005,
            ),
            make_property(
                platform="booking",
                listing_id="unit1",
                name="Apartments Alpenblick 1",
                property_type="apartment",
                max_occupancy=4,
                lat=47.3901,
                lng=13.6801,
            ),
            make_property(
                platform="booking",
                listing_id="unit2",
                name="Apartments Alpenblick 2",
                property_type="apartment",
                max_occupancy=4,
                lat=47.39011,
                lng=13.68011,
            ),
        ]
        for prop in props:
            prop["in_radius"] = True
            prop["key"] = analysis.property_key(prop)
        clusters, _ = analysis.cluster_properties(props, radius_m=200)
        multi = [cluster for cluster in clusters if cluster["size"] > 1]
        self.assertEqual(len(multi), 1)
        cluster = multi[0]
        self.assertEqual(cluster["size"], 4)
        self.assertTrue(cluster["cross_platform_duplicate"])
        self.assertTrue(cluster["same_platform_multiple_units"])


class PriceTests(unittest.TestCase):
    def test_price_relation_marks_large_delta(self) -> None:
        relation, delta = analysis.price_relation(
            {"totalPrice": 1000},
            {"totalPrice": 1200},
        )
        self.assertEqual(relation, "quote_higher")
        self.assertAlmostEqual(delta, 0.2)

    def test_no_availability_after_search_price(self) -> None:
        prop = make_property(
            platform="booking",
            listing_id="apartments1",
            name="Apartments Alpenblick",
            property_type="apartment",
            max_occupancy=4,
            total=900,
        )
        prop.update(
            {
                "key": "booking:apartments1",
                "observations": [
                    {
                        "search_key": "whole",
                        "search_label": "celá skupina",
                        "occupancy": {"adults": 12, "children": 3, "child_ages": [6, 9, 12]},
                        "price": {"totalPrice": 900, "currency": "EUR", "nights": 4},
                    }
                ],
            }
        )
        checks = analysis.build_price_checks(
            [prop],
            [
                {
                    "candidate_key": "booking:apartments1",
                    "label": "full",
                    "occupancy": {"adults": 12, "children": 3, "child_ages": [6, 9, 12]},
                    "envelope": None,
                    "error": {"code": "no_availability", "message": "No single room fits"},
                    "raw_file": None,
                }
            ],
            group_total=15,
            requested_currency="EUR",
        )
        self.assertEqual(len(checks), 1)
        self.assertIn(
            "search_price_but_single_unit_no_availability",
            checks[0]["flags"],
        )


class AnswerQualityTests(unittest.TestCase):
    def test_all_searches_failed_does_not_look_like_empty_market(self) -> None:
        searches = [
            {
                "key": "whole",
                "label": "celá skupina",
                "ok": False,
                "error": {
                    "type": "upstream_unavailable",
                    "code": "all_actors_failed",
                    "message": "All actors failed for booking.search.",
                    "request_id": "req_test",
                },
                "raw_file": "raw/0001_search_whole.json",
                "warnings": [],
            }
        ]
        answers = analysis.build_answers(
            config={"platforms": ["airbnb", "booking"], "limit": 10},
            properties=[],
            clusters=[],
            price_checks=[],
            credits={
                "total": 0,
                "search": 0,
                "listing": 0,
                "price": 0,
                "search_worst_case": 30,
                "search_count": 1,
                "probe_worst_case": 30,
            },
            searches=searches,
        )
        self.assertTrue(answers["data_quality"]["all_failed"])
        self.assertIn("NELZE URČIT", answers["q1_scope"]["status"])
        self.assertIn("NELZE", answers["q5_credit_cost"]["status"])
        self.assertIn("requestId", answers["q1_scope"]["text"])
        self.assertEqual(answers["data_quality"]["errors"][0]["request_id"], "req_test")


class CreditTests(unittest.TestCase):
    def test_search_worst_case(self) -> None:
        self.assertEqual(analysis.search_worst_case(["airbnb", "booking"], 10), 30)
        self.assertEqual(analysis.search_worst_case(["airbnb", "booking"], 40), 120)
        self.assertEqual(analysis.search_worst_case(["google"], 10), 15)
        self.assertEqual(analysis.search_worst_case(["vrbo"], 10), 10)

    def test_credit_summary(self) -> None:
        config = {"platforms": ["airbnb", "booking"], "limit": 10}
        summary = analysis.build_credit_summary(
            searches=[
                {"key": "whole", "label": "celá", "credits": 25, "count": 15},
                {"key": "sub", "label": "menší", "credits": 10, "count": 5},
            ],
            listing_probes=[{"credits": 3}],
            price_checks=[{"credits": 3}, {"credits": 3}],
            config=config,
        )
        self.assertEqual(summary["search"], 35)
        self.assertEqual(summary["listing"], 3)
        self.assertEqual(summary["price"], 6)
        self.assertEqual(summary["total"], 44)
        self.assertEqual(summary["search_worst_case"], 30)


if __name__ == "__main__":
    unittest.main()
