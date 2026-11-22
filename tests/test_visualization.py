from __future__ import annotations

import json
import unittest
from pathlib import Path

ROLE_BEDROOMS = {2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 4, 10: 4}
PAIR_SPLITS = {"4+6", "5+5", "3+7", "2+8"}

ADULTS = 10
MAX_RESORT_KM = 15.0
MAX_UNIT_KM = 1.0
MAX_RESORT_KM_SUPPORTED = 25.0
MAX_UNIT_KM_SUPPORTED = 1.0


class VisualizationDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path("docs/data/pairs.json")
        cls.data = json.loads(path.read_text(encoding="utf-8"))

    def test_options_are_present(self) -> None:
        self.assertGreater(len(self.data["options"]), 0)
        for option in self.data["options"]:
            self.assertIn(option["provider"], {"Airbnb", "Booking", "Mix"})
            self.assertGreater(option["total"], 0)

    def test_stay_metadata(self) -> None:
        stays = self.data["stays"]
        self.assertEqual(set(stays), {"5n"})
        self.assertEqual(stays["5n"]["check_in"], "2027-02-01")
        self.assertEqual(stays["5n"]["check_out"], "2027-02-06")
        self.assertEqual(stays["5n"]["nights"], 5)
        for option in self.data["options"]:
            self.assertIn(option["stay"], stays)
            self.assertEqual(option["nights"], stays[option["stay"]]["nights"])
            self.assertEqual(option["check_in"], stays[option["stay"]]["check_in"])
            self.assertEqual(option["check_out"], stays[option["stay"]]["check_out"])

    def test_split_matches_units(self) -> None:
        for option in self.data["options"]:
            roles = [str(unit["role"]) for unit in option["units"]]
            if option["split"] in {"celý objekt", "více pokojů"}:
                self.assertEqual(roles, [str(ADULTS)])
            else:
                self.assertIn(option["split"], PAIR_SPLITS)
                self.assertEqual(len(roles), 2)
                self.assertEqual(sum(int(role) for role in roles), ADULTS)
                self.assertEqual(option["split"], "+".join(roles))

    def test_capacity_and_bedrooms(self) -> None:
        for option in self.data["options"]:
            self.assertEqual(option["total_bedrooms"], sum(unit["bedrooms"] for unit in option["units"]))
            for unit in option["units"]:
                role = int(unit["role"])
                self.assertIn(role, ROLE_BEDROOMS)
                self.assertEqual(unit["capacity"], role)
                if unit["provider"] == "Booking" and unit.get("type") == "entire_home":
                    # Booking u celých domů často uvádí jen část ložnic.
                    self.assertGreaterEqual(unit["bedrooms"], 1)
                else:
                    self.assertGreaterEqual(unit["bedrooms"], ROLE_BEDROOMS[role])

    def test_distance_filters(self) -> None:
        self.assertEqual(self.data["assumptions"]["max_resort_km"], MAX_RESORT_KM)
        self.assertEqual(self.data["assumptions"]["max_unit_km"], MAX_UNIT_KM)
        near = 0
        for option in self.data["options"]:
            self.assertIsNotNone(option["max_resort_km"])
            self.assertLessEqual(option["max_resort_km"], MAX_RESORT_KM_SUPPORTED)
            self.assertIsNotNone(option["max_unit_km"])
            self.assertLessEqual(option["max_unit_km"], MAX_UNIT_KM_SUPPORTED)
            for unit in option["units"]:
                self.assertIsNotNone(unit["resort_km"])
                self.assertLessEqual(unit["resort_km"], MAX_RESORT_KM_SUPPORTED)
            if option["max_resort_km"] <= MAX_RESORT_KM and option["max_unit_km"] <= MAX_UNIT_KM:
                near += 1
            if option["split"] == "celý objekt":
                self.assertEqual(option["max_unit_km"], 0.0)
        self.assertGreater(near, 0, "chybí varianty v základním filtru 15/10 km")

    def test_price_and_czk_per_person(self) -> None:
        for option in self.data["options"]:
            total = sum(unit["price"] for unit in option["units"])
            self.assertLessEqual(abs(total - option["total"]), 0.01)
            self.assertEqual(option["czk_per_person"], round(option["total"] * 25 / ADULTS))

    def test_options_have_at_most_two_units(self) -> None:
        for option in self.data["options"]:
            self.assertLessEqual(len(option["units"]), 2)

    def test_providers_are_represented(self) -> None:
        providers = {option["provider"] for option in self.data["options"]}
        self.assertIn("Airbnb", providers)
        self.assertTrue(providers <= {"Airbnb", "Booking", "Mix"})

    def test_option_limit_per_area_and_stay(self) -> None:
        counts: dict[tuple[str, str], int] = {}
        for option in self.data["options"]:
            key = (option["stay"], option["area"])
            counts[key] = counts.get(key, 0) + 1
        for key, count in counts.items():
            self.assertLessEqual(count, self.data["assumptions"]["options_per_area"], key)

    def test_all_resorts_have_metadata(self) -> None:
        for name, resort in self.data["resorts"].items():
            self.assertTrue(name)
            self.assertTrue(resort["color"].startswith("#"))
            center = resort.get("center")
            self.assertIsNotNone(center, f"{name} nemá center")
            self.assertIn("lat", center)
            self.assertIn("lng", center)
            self.assertGreaterEqual(len(resort["points"]), 2, f"{name} má málo nástupních stanic")
            for point in resort["points"]:
                self.assertIn("lat", point)
                self.assertIn("lng", point)
                self.assertIn("name", point)

    def test_ids_and_shares_are_unique(self) -> None:
        ids = [option["id"] for option in self.data["options"]]
        self.assertEqual(len(ids), len(set(ids)))
        shares = [option["share"] for option in self.data["options"]]
        self.assertEqual(len(shares), len(set(shares)))

    def test_images_are_optional_http_urls(self) -> None:
        for option in self.data["options"]:
            for unit in option["units"]:
                image = unit.get("image")
                if image:
                    self.assertTrue(image.startswith("http"), image)

    def test_ratings_are_positive_or_null(self) -> None:
        for option in self.data["options"]:
            for unit in option["units"]:
                rating = unit.get("rating")
                if rating is not None:
                    self.assertGreater(rating, 0)


if __name__ == "__main__":
    unittest.main()
