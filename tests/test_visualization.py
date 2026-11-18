from __future__ import annotations

import json
import unittest
from pathlib import Path


class VisualizationDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path("docs/data/pairs.json")
        cls.data = json.loads(path.read_text(encoding="utf-8"))

    def test_pairs_have_required_roles_and_bedrooms(self) -> None:
        self.assertGreater(len(self.data["pairs"]), 0)
        for pair in self.data["pairs"]:
            roles = {unit["role"]: unit for unit in pair["units"]}
            self.assertEqual(set(roles), {"7", "5"})
            self.assertGreaterEqual(roles["7"]["bedrooms"], 3)
            self.assertGreaterEqual(roles["5"]["bedrooms"], 2)
            self.assertGreaterEqual(roles["7"]["capacity"], 7)
            self.assertGreaterEqual(roles["5"]["capacity"], 5)
            self.assertLessEqual(pair["total"], 3500)
            self.assertLessEqual(pair["max_resort_km"], 25.0)
            self.assertIn(pair["provider"], {"Airbnb", "Booking", "Mix"})
            self.assertGreaterEqual(pair["distance_units_km"], 0.0)
            self.assertNotEqual(roles["7"]["id"], roles["5"]["id"])
            expected_czk = round(pair["total"] * 25 / 12)
            self.assertLessEqual(abs(expected_czk - pair["czk_per_person"]), 1)

    def test_new_resorts_are_present(self) -> None:
        for name in ["Katschberg – Aineck", "Obertauern", "Hochkönig", "Nassfeld"]:
            self.assertIn(name, self.data["resorts"])

    def test_providers_are_represented(self) -> None:
        providers = {pair["provider"] for pair in self.data["pairs"]}
        self.assertIn("Airbnb", providers)
        self.assertIn("Booking", providers)

    def test_local_booking_pairs_are_valid(self) -> None:
        items = self.data.get("booking_local") or []
        self.assertGreater(len(items), 0)
        for pair in items:
            roles = {unit["role"]: unit for unit in pair["units"]}
            self.assertEqual(set(roles), {"7", "5"})
            self.assertGreaterEqual(roles["7"]["bedrooms"], 3)
            self.assertGreaterEqual(roles["5"]["bedrooms"], 2)
            self.assertLessEqual(pair["total"], 3500)
            self.assertEqual(roles["7"]["provider"], "Booking")
            self.assertEqual(roles["5"]["provider"], "Booking")

    def test_multi_pairs_are_valid(self) -> None:
        items = self.data.get("multi_pairs") or []
        self.assertGreater(len(items), 0)
        for combo in items:
            roles = [int(unit["role"]) for unit in combo["units"]]
            self.assertGreaterEqual(len(roles), 2)
            self.assertLessEqual(len(roles), 4)
            self.assertEqual(sum(roles), 12)
            self.assertGreaterEqual(combo["total_bedrooms"], 5)
            for unit in combo["units"]:
                self.assertGreaterEqual(unit["bedrooms"], {2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 4, 9: 4, 10: 4}[int(unit["role"])])
            self.assertLessEqual(combo["total"], 3500)

    def test_unified_options_are_valid(self) -> None:
        items = self.data.get("options") or []
        self.assertGreater(len(items), 0)
        for option in items:
            roles = [int(unit["role"]) for unit in option["units"]]
            self.assertGreaterEqual(len(roles), 2)
            self.assertLessEqual(len(roles), 4)
            self.assertEqual(sum(roles), 12)
            self.assertEqual(option["split"], "+".join(str(role) for role in roles))
            self.assertIn(option["provider"], {"Airbnb", "Booking", "Mix"})
            self.assertLessEqual(option["total"], 3500)
            self.assertGreaterEqual(option["total_bedrooms"], 5)
            ids = [unit["id"] for unit in option["units"]]
            self.assertEqual(len(ids), len(set(ids)))

    def test_best_options_are_valid(self) -> None:
        items = self.data.get("best_options") or []
        self.assertEqual(len(items), len(self.data["resorts"]))
        for item in items:
            for key in ("best_two", "best_multi"):
                option = item.get(key)
                if not option:
                    continue
                roles = [int(unit["role"]) for unit in option["units"]]
                self.assertEqual(sum(roles), 12)
                self.assertLessEqual(option["total"], 3500)
                self.assertGreaterEqual(sum(unit["bedrooms"] for unit in option["units"]), 5)

    def test_all_resorts_have_metadata(self) -> None:
        for name, resort in self.data["resorts"].items():
            self.assertTrue(name)
            self.assertTrue(resort["color"].startswith("#"))
            self.assertGreaterEqual(len(resort["points"]), 1)
            for point in resort["points"]:
                self.assertIn("lat", point)
                self.assertIn("lng", point)
                self.assertIn("name", point)

    def test_pair_ids_are_unique(self) -> None:
        ids = [pair["id"] for pair in self.data["pairs"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_images_are_optional_http_urls(self) -> None:
        for pair in self.data["pairs"]:
            for unit in pair["units"]:
                image = unit.get("image")
                if image:
                    self.assertTrue(image.startswith("http"), image)


if __name__ == "__main__":
    unittest.main()
