#!/usr/bin/env python3
"""Staví statickou vizualizaci ubytování pro 10 osob.

Vstupem jsou kombinace z `scripts/combine_units.py`
(`data/trip_search/combos_2027-02-01/combos_4n.json` a `combos_5n.json`),
výstupem `docs/data/pairs.json` a `docs/data/pairs.js` pro stránku v `docs/`.

Ceny jsou za celý pobyt, vzdálenosti vzdušnou čarou. Na stránku jde pro každé
středisko a termín 40 variant s nejlepším skóre; plná data zůstávají v JSON
souborech kombinací.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_units import LOCAL_AIRBNB, RESORTS, distance_km  # noqa: E402

COMBOS = ROOT / "data" / "trip_search" / "combos_2027-02-01"
COMBOS_WIDE = ROOT / "data" / "trip_search" / "combos_2027-02-01_wide"
OUT = ROOT / "docs" / "data"
DEFAULT_MAX_TOTAL = 3500


STAYS = {
    "4n": {
        "label": "4 noci (1. 2. – 5. 2.)",
        "check_in": "2027-02-01",
        "check_out": "2027-02-05",
        "nights": 4,
    },
    "5n": {
        "label": "5 nocí (1. 2. – 6. 2.)",
        "check_in": "2027-02-01",
        "check_out": "2027-02-06",
        "nights": 5,
    },
}

ADULTS = 10
CZK_PER_EUR = 25
NEAR_RESORT_KM = 15.0
NEAR_UNIT_KM = 10.0
LIMIT_NEAR = 40
LIMIT_FAR = 30
TRIPLE_NEAR = 20
TRIPLE_FAR = 10
WHOLE_NEAR = 15
WHOLE_FAR = 5
LIMIT_PER_AREA = LIMIT_NEAR + LIMIT_FAR + TRIPLE_NEAR + TRIPLE_FAR + WHOLE_NEAR + WHOLE_FAR


def nearest_point(area: str, lat: float | None, lng: float | None) -> dict[str, Any]:
    points = RESORTS[area]["points"]
    if lat is None or lng is None:
        return points[0]
    return min(points, key=lambda point: distance_km((lat, lng), (point["lat"], point["lng"])))


def load_airbnb_images() -> dict[str, str]:
    images: dict[str, str] = {}
    for path in LOCAL_AIRBNB.glob("*.json"):
        for item in json.loads(path.read_text(encoding="utf-8")):
            room_id = str(item.get("room_id"))
            if room_id in images:
                continue
            url = ((item.get("images") or [{}])[0]).get("url")
            if url:
                images[room_id] = url
    return images


def map_unit(unit: dict[str, Any], area: str, images: dict[str, str]) -> dict[str, Any]:
    lat, lng = unit.get("lat"), unit.get("lng")
    point = nearest_point(area, lat, lng)
    role = unit.get("capacity")
    provider = unit.get("provider")
    rating = unit.get("rating") or None
    reviews = unit.get("reviews") or None
    return {
        "provider": provider,
        "role": str(role),
        "id": unit.get("id"),
        "title": unit.get("title"),
        "url": unit.get("url"),
        "price": unit.get("price"),
        "capacity": role,
        "bedrooms": unit.get("bedrooms"),
        "lat": lat,
        "lng": lng,
        "resort": area,
        "resort_point": point,
        "resort_km": unit.get("resort_km"),
        "image": images.get(str(unit.get("id"))) if provider == "Airbnb" else None,
        "rating": rating,
        "reviews": reviews,
        "location": unit.get("location"),
        "type": unit.get("lodging_kind") if provider == "Booking" else "Airbnb",
    }


def option_score(item: dict[str, Any]) -> float:
    resort_km = item.get("max_resort_km")
    unit_km = item.get("max_unit_km")
    return (
        item["total"]
        + (resort_km if resort_km is not None else 15) * 25
        + (unit_km if unit_km is not None else 10) * 5
    )


def build_option(item: dict[str, Any], stay: str, stay_info: dict[str, Any], images: dict[str, str]) -> dict[str, Any]:
    area = item["area"]
    units = [map_unit(unit, area, images) for unit in item["units"]]
    total = float(item["total"])
    split = "celý objekt" if item["split"] == str(ADULTS) else item["split"]
    return {
        "id": item["id"],
        "stay": stay,
        "share": hashlib.sha1(
            (stay + "|" + "|".join(sorted(str(unit["id"]) for unit in units))).encode("utf-8")
        ).hexdigest()[:12],
        "area": area,
        "split": split,
        "provider": item["provider"],
        "total": round(total, 2),
        "czk_per_person": round(total * CZK_PER_EUR / ADULTS),
        "total_bedrooms": item["total_bedrooms"],
        "max_resort_km": item.get("max_resort_km"),
        "max_unit_km": item.get("max_unit_km"),
        "same_building": item.get("same_building", False),
        "check_in": stay_info["check_in"],
        "check_out": stay_info["check_out"],
        "nights": stay_info["nights"],
        "units": units,
        "score": round(option_score(item), 2),
    }


def load_items(stay: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, folder in enumerate((COMBOS, COMBOS_WIDE)):
        path = folder / f"combos_{stay}.json"
        if not path.exists():
            if index == 0:
                raise SystemExit(f"Chybí {path}. Spusť nejdřív scripts/combine_units.py.")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        items.extend(data["pairs"])
        items.extend(data.get("triples") or [])
        items.extend(data["whole"])
    return items


def is_near(item: dict[str, Any]) -> bool:
    resort_km = item.get("max_resort_km")
    unit_km = item.get("max_unit_km")
    return (
        resort_km is not None
        and resort_km <= NEAR_RESORT_KM
        and unit_km is not None
        and unit_km <= NEAR_UNIT_KM
    )


def select_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = tuple(sorted(str(unit["id"]) for unit in item["units"]))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    def split_bucket(count: int, near_limit: int, far_limit: int) -> list[dict[str, Any]]:
        pool = [item for item in unique if len(item["units"]) == count]
        near = sorted((item for item in pool if is_near(item)), key=option_score)[:near_limit]
        far = sorted((item for item in pool if not is_near(item)), key=option_score)[:far_limit]
        return near + far

    return (
        split_bucket(1, WHOLE_NEAR, WHOLE_FAR)
        + split_bucket(2, LIMIT_NEAR, LIMIT_FAR)
        + split_bucket(3, TRIPLE_NEAR, TRIPLE_FAR)
    )

def main() -> int:
    parser = argparse.ArgumentParser(description="Staví vizualizaci ubytování pro 10 osob.")
    parser.add_argument(
        "--max-total",
        type=float,
        default=DEFAULT_MAX_TOTAL,
        help="Vyřadit varianty dražší než tato částka (výchozí 3500 €).",
    )
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    images = load_airbnb_images()
    options: list[dict[str, Any]] = []
    for stay, stay_info in STAYS.items():
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in load_items(stay):
            if item["total"] > args.max_total:
                continue
            grouped.setdefault(item["area"], []).append(item)
        for area, items in grouped.items():
            for item in select_items(items):
                options.append(build_option(item, stay, stay_info, images))

    options.sort(key=lambda option: (option["stay"], option["area"], option["score"]))
    for index, option in enumerate(options, start=1):
        option["id"] = f"o{index:04d}"

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "assumptions": {
            "check_in": STAYS["4n"]["check_in"],
            "check_out": STAYS["4n"]["check_out"],
            "nights": STAYS["4n"]["nights"],
            "adults": ADULTS,
            "split": "10 (celý objekt), dvojice 4+6, 5+5, 3+7, 2+8 nebo trojice 3+3+4, 2+4+4, 2+3+5, 2+2+6",
            "bedrooms": "u dvojic alespoň 2–4 ložnice podle velikosti jednotky",
            "max_resort_km": NEAR_RESORT_KM,
            "max_unit_km": NEAR_UNIT_KM,
            "max_resort_km_supported": 25,
            "max_unit_km_supported": 50,
            "price_note": "Ceny jsou za celý pobyt podle data hledání; mohou se změnit.",
            "distance_note": "Vzdálenost k lanovce je silniční trasa (OSRM, auto); vzdálenost mezi jednotkami je vzdušnou čarou. V základu 15 km po silnici a 10 km mezi jednotkami, v UI lze rozšířit.",
            "budget_total": args.max_total,
            "budget_czk_per_person": 5000,
            "czk_per_eur": CZK_PER_EUR,
            "options_per_area": LIMIT_PER_AREA,
        },
        "stays": STAYS,
        "resorts": RESORTS,
        "options": options,
    }
    (OUT / "pairs.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "pairs.js").write_text(
        "window.PAIR_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"Variant: {len(options)}")
    counts: dict[str, int] = {}
    for option in options:
        key = f"{option['stay']} · {option['area']}"
        counts[key] = counts.get(key, 0) + 1
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")
    print(f"Zapsáno: {OUT / 'pairs.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
