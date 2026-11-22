#!/usr/bin/env python3
"""Skládá kombinace ubytování pro 10 osob.

Vezme výstupy lokálních hledačů (`search_local_airbnb.py`,
`search_local_booking.py`) a sestaví:
- celé objekty pro 10 osob (role 10),
- dvojice menších jednotek 4+6, 5+5, 3+7 a 2+8 osob ve stejném středisku.

Ceny jsou za celý pobyt. Vzdálenost od střediska i mezi jednotkami je vzdušnou
čarou. Booking souřadnice nevrací, takže se u něj používá vzdálenost „X km from“
z detailu nabídky; vzdálenost mezi dvěma Booking jednotkami spočítat nelze a
takové dvojice se ve výchozím nastavení vyřazují (přepínač
`--allow-unknown-distance`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from itertools import product
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from local_units import (  # noqa: E402
    LOCAL_AIRBNB,
    PRICE_CAP,
    RESORTS,
    distance_km,
    load_booking_role,
    parse_local_airbnb_unit,
)

PAIRS = [(4, 6), (5, 5), (3, 7), (2, 8)]
TRIPLES = [(3, 3, 4), (2, 4, 4), (2, 3, 5), (2, 2, 6)]
TRIPLE_CANDIDATES = 25
WHOLE_ROLE = 10
MAX_RESORT_KM = 15.0
MAX_UNIT_KM = 10.0
SAME_BUILDING_KM = 0.2

STAYS = {
    "4n": {"check_in": "2027-02-01", "check_out": "2027-02-05", "nights": 4, "suffix": ""},
    "5n": {"check_in": "2027-02-01", "check_out": "2027-02-06", "nights": 5, "suffix": "_5n"},
}

OUT = ROOT / "data" / "trip_search" / "combos_2027-02-01"
ROAD_CACHE = ROOT / "data" / "trip_search" / "road_distances.json"
PAIR_CACHE = ROOT / "data" / "trip_search" / "road_pair_distances.json"


def load_road_distances() -> dict[str, dict[str, Any]]:
    if not ROAD_CACHE.exists():
        return {}
    data = json.loads(ROAD_CACHE.read_text(encoding="utf-8"))
    return data.get("distances") or {}


ROAD = load_road_distances()


def load_airbnb(role: int, suffix: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(LOCAL_AIRBNB.glob(f"*_{role}{suffix}.json")):
        if suffix and path.stem.endswith(f"_{role}"):
            continue
        for item in json.loads(path.read_text(encoding="utf-8")):
            unit = parse_local_airbnb_unit(item, role)
            if unit is None:
                continue
            grouped.setdefault(unit["resort"], []).append(unit)
    return grouped


def collect_units(suffix: str) -> dict[str, dict[str, list[dict[str, Any]]]]:
    roles = sorted({WHOLE_ROLE, *(role for pair in PAIRS for role in pair)})
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for role in roles:
        for loader in (load_airbnb, load_booking_role):
            for resort, units in loader(role, suffix).items():
                for unit in units:
                    apply_road(unit)
                grouped.setdefault(resort, {}).setdefault(str(role), []).extend(units)
    for resort in grouped:
        for role, units in grouped[resort].items():
            unique = {unit["id"]: unit for unit in units}
            grouped[resort][role] = sorted(unique.values(), key=lambda unit: unit["price"])
    return grouped


def compact(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": unit["provider"],
        "id": unit["id"],
        "title": " ".join(str(unit["title"]).split()),
        "url": unit["url"],
        "price": unit["price"],
        "bedrooms": unit["bedrooms"],
        "capacity": unit["capacity"],
        "resort": unit["resort"],
        "resort_km": unit.get("resort_km"),
        "lat": unit.get("lat"),
        "lng": unit.get("lng"),
        "rating": unit.get("rating"),
        "reviews": unit.get("reviews"),
        "location": unit.get("location"),
        "lodging_kind": unit.get("lodging_kind"),
        "image": unit.get("image"),
    }


def unit_distance(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    if None in (left.get("lat"), left.get("lng"), right.get("lat"), right.get("lng")):
        return None
    return distance_km(
        (float(left["lat"]), float(left["lng"])),
        (float(right["lat"]), float(right["lng"])),
    )


def load_pair_distances() -> dict[str, dict[str, Any]]:
    if not PAIR_CACHE.exists():
        return {}
    data = json.loads(PAIR_CACHE.read_text(encoding="utf-8"))
    result = {}
    for resort, payload in (data.get("distances") or {}).items():
        result[resort] = {
            "index": {str(unit_id): position for position, unit_id in enumerate(payload["ids"])},
            "km": payload["km"],
        }
    return result


PAIR_DISTANCES = load_pair_distances()


def apply_road(unit: dict[str, Any]) -> None:
    road = ROAD.get(unit["id"])
    if not road:
        return
    unit["resort_km"] = road["km"]
    unit["distance_mode"] = "road"
    lift = next(
        (
            point
            for point in RESORTS[unit["resort"]]["points"]
            if point["name"] == road["lift"]
        ),
        None,
    )
    if lift is not None:
        unit["resort_point"] = lift


def road_distance(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    payload = PAIR_DISTANCES.get(left["resort"])
    if payload is None:
        return None
    left_index = payload["index"].get(str(left["id"]))
    right_index = payload["index"].get(str(right["id"]))
    if left_index is None or right_index is None:
        return None
    value = payload["km"][left_index][right_index]
    return None if value is None else float(value)


def within_resort(unit: dict[str, Any], max_resort_km: float, allow_unknown: bool) -> bool:
    km = unit.get("resort_km")
    if km is None:
        return allow_unknown
    return km <= max_resort_km


def build_pairs(
    resort: str,
    grouped: dict[str, list[dict[str, Any]]],
    label: str,
    nights: int,
    *,
    max_resort_km: float,
    max_unit_km: float,
    allow_unknown: bool,
) -> list[dict[str, Any]]:
    result = []
    seen: set[frozenset[str]] = set()
    for left_role, right_role in PAIRS:
        left_units = grouped.get(str(left_role), [])
        right_units = grouped.get(str(right_role), [])
        if not left_units or not right_units:
            continue
        min_left = min(unit["price"] for unit in left_units)
        min_right = min(unit["price"] for unit in right_units)
        left_units = [unit for unit in left_units if unit["price"] + min_right <= PRICE_CAP]
        right_units = [unit for unit in right_units if unit["price"] + min_left <= PRICE_CAP]
        for left, right in product(left_units, right_units):
            if left["id"] == right["id"]:
                continue
            if not within_resort(left, max_resort_km, allow_unknown):
                continue
            if not within_resort(right, max_resort_km, allow_unknown):
                continue
            crow = unit_distance(left, right)
            road = road_distance(left, right)
            distance = road if road is not None else crow
            if distance is None:
                if not allow_unknown:
                    continue
            elif distance > max_unit_km:
                continue
            key = frozenset((left["id"], right["id"]))
            if key in seen:
                continue
            total = left["price"] + right["price"]
            if total > PRICE_CAP:
                continue
            seen.add(key)
            providers = {left["provider"], right["provider"]}
            resort_kms = [left.get("resort_km"), right.get("resort_km")]
            max_resort = (
                round(max(resort_kms), 2) if all(value is not None for value in resort_kms) else None
            )
            result.append(
                {
                    "area": resort,
                    "split": f"{left_role}+{right_role}",
                    "provider": "Airbnb" if providers == {"Airbnb"} else "Booking" if providers == {"Booking"} else "Mix",
                    "stay": label,
                    "nights": nights,
                    "total": round(total, 2),
                    "per_person_night": round(total / nights / 10, 2),
                    "total_bedrooms": left["bedrooms"] + right["bedrooms"],
                    "max_unit_km": None if distance is None else round(distance, 2),
                    "max_resort_km": max_resort,
                    "distance_unknown": distance is None,
                    "distance_mode": "road" if road is not None else "crow",
                    "same_building": crow is not None and crow <= SAME_BUILDING_KM,
                    "units": [compact(left), compact(right)],
                }
            )
    result.sort(key=lambda item: item["total"])
    return result


def build_triples(
    resort: str,
    grouped: dict[str, list[dict[str, Any]]],
    label: str,
    nights: int,
    *,
    max_resort_km: float,
    max_unit_km: float,
    allow_unknown: bool,
) -> list[dict[str, Any]]:
    result = []
    seen: set[tuple[str, ...]] = set()
    for pattern in TRIPLES:
        role_lists = []
        lists = []
        for role in pattern:
            units = grouped.get(str(role), [])
            if not units:
                break
            others = [
                min(unit["price"] for unit in grouped.get(str(other), []))
                for other in pattern
                if other != role
            ]
            budget = PRICE_CAP - sum(others)
            role_lists.append([unit for unit in units if unit["price"] <= budget])
        else:
            if all(role_lists):
                lists = [
                    sorted(
                        units,
                        key=lambda unit: unit["price"] + (unit.get("resort_km") or 20) * 20,
                    )[:TRIPLE_CANDIDATES]
                    for units in role_lists
                ]
            else:
                lists = []
        if not lists:
            continue
        for combo in product(*lists):
            ids = [unit["id"] for unit in combo]
            if len(set(ids)) < len(combo):
                continue
            if not all(within_resort(unit, max_resort_km, allow_unknown) for unit in combo):
                continue
            key = tuple(sorted(ids))
            if key in seen:
                continue
            distances = []
            crows = []
            road_flags = []
            allowed = True
            for left_index, right_index in ((0, 1), (0, 2), (1, 2)):
                left, right = combo[left_index], combo[right_index]
                crow = unit_distance(left, right)
                road = road_distance(left, right)
                distance = road if road is not None else crow
                if distance is None:
                    if not allow_unknown:
                        allowed = False
                        break
                    continue
                if distance > max_unit_km:
                    allowed = False
                    break
                distances.append(distance)
                crows.append(crow)
                road_flags.append(road is not None)
            if not allowed or not distances:
                continue
            total = sum(unit["price"] for unit in combo)
            if total > PRICE_CAP:
                continue
            seen.add(key)
            providers = {unit["provider"] for unit in combo}
            resort_kms = [unit.get("resort_km") for unit in combo]
            max_resort = (
                round(max(resort_kms), 2) if all(value is not None for value in resort_kms) else None
            )
            result.append(
                {
                    "area": resort,
                    "split": "+".join(str(role) for role in pattern),
                    "provider": "Airbnb" if providers == {"Airbnb"} else "Booking" if providers == {"Booking"} else "Mix",
                    "stay": label,
                    "nights": nights,
                    "total": round(total, 2),
                    "per_person_night": round(total / nights / 10, 2),
                    "total_bedrooms": sum(unit["bedrooms"] for unit in combo),
                    "max_unit_km": round(max(distances), 2),
                    "max_resort_km": max_resort,
                    "distance_unknown": False,
                    "distance_mode": "road" if all(road_flags) else "crow",
                    "same_building": all(crow is not None and crow <= SAME_BUILDING_KM for crow in crows),
                    "units": [compact(unit) for unit in combo],
                }
            )
    result.sort(key=lambda item: item["total"])
    return result


def build_whole(
    resort: str,
    grouped: dict[str, list[dict[str, Any]]],
    label: str,
    nights: int,
    *,
    max_resort_km: float,
    allow_unknown: bool,
) -> list[dict[str, Any]]:
    result = []
    for unit in grouped.get(str(WHOLE_ROLE), []):
        # U Bookingu bereme jen skutečné celé domy; hotely s více pokoji nejsou
        # jedna jednotka pro 10 osob.
        if unit["provider"] == "Booking" and unit.get("lodging_kind") != "entire_home":
            continue
        if (unit["bedrooms"] or 0) > 10:
            continue
        if unit["price"] > PRICE_CAP:
            continue
        if not within_resort(unit, max_resort_km, allow_unknown):
            continue
        total = unit["price"]
        result.append(
            {
                "area": resort,
                "split": str(WHOLE_ROLE),
                "provider": unit["provider"],
                "stay": label,
                "nights": nights,
                "total": round(total, 2),
                "per_person_night": round(total / nights / 10, 2),
                "total_bedrooms": unit["bedrooms"],
                "max_unit_km": 0.0,
                "max_resort_km": unit.get("resort_km"),
                "distance_unknown": unit.get("resort_km") is None,
                "same_building": False,
                "units": [compact(unit)],
            }
        )
    result.sort(key=lambda item: item["total"])
    return result


def format_units(item: dict[str, Any]) -> str:
    parts = []
    for unit in item["units"]:
        distance = unit.get("resort_km")
        suffix = f", {distance} km" if distance is not None else ""
        parts.append(f"{unit['provider']} {unit['title']} ({unit['price']:.0f} €{suffix})")
    return " + ".join(parts)


def cap_per_area(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Nechá `limit` nejlevnějších dvojic na středisko (0 = všechny)."""
    if limit <= 0:
        return items
    by_area: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_area.setdefault(item["area"], []).append(item)
    selected: list[dict[str, Any]] = []
    for area_items in by_area.values():
        selected.extend(sorted(area_items, key=lambda item: item["total"])[:limit])
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Kombinace ubytování pro 10 osob.")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=0,
        help="Kolik nejlevnějších dvojic uložit na středisko (0 = všechny).",
    )
    parser.add_argument(
        "--max-triples",
        type=int,
        default=150,
        help="Kolik nejlevnějších trojic uložit na středisko (0 = všechny).",
    )
    parser.add_argument(
        "--max-resort-km",
        type=float,
        default=MAX_RESORT_KM,
        help="Max. vzdálenost jednotky od střediska v km (vzdušnou čarou).",
    )
    parser.add_argument(
        "--max-unit-km",
        type=float,
        default=MAX_UNIT_KM,
        help="Max. vzdálenost mezi jednotkami ve dvojici v km.",
    )
    parser.add_argument(
        "--allow-unknown-distance",
        action="store_true",
        help="Ponechat i jednotky/dvojice bez známé vzdálenosti (typicky Booking).",
    )
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {}
    for label, stay in STAYS.items():
        suffix = stay["suffix"]
        grouped = collect_units(suffix)
        pairs: list[dict[str, Any]] = []
        triples: list[dict[str, Any]] = []
        whole: list[dict[str, Any]] = []
        for resort, roles in grouped.items():
            triples.extend(
                build_triples(
                    resort,
                    roles,
                    label,
                    stay["nights"],
                    max_resort_km=args.max_resort_km,
                    max_unit_km=args.max_unit_km,
                    allow_unknown=args.allow_unknown_distance,
                )
            )
            pairs.extend(
                build_pairs(
                    resort,
                    roles,
                    label,
                    stay["nights"],
                    max_resort_km=args.max_resort_km,
                    max_unit_km=args.max_unit_km,
                    allow_unknown=args.allow_unknown_distance,
                )
            )
            whole.extend(
                build_whole(
                    resort,
                    roles,
                    label,
                    stay["nights"],
                    max_resort_km=args.max_resort_km,
                    allow_unknown=args.allow_unknown_distance,
                )
            )
        pairs.sort(key=lambda item: (item["area"], item["total"]))
        triples.sort(key=lambda item: (item["area"], item["total"]))
        whole.sort(key=lambda item: (item["area"], item["total"]))
        pairs = cap_per_area(pairs, args.max_pairs)
        triples = cap_per_area(triples, args.max_triples)
        for index, item in enumerate(pairs, start=1):
            item["id"] = f"{label}-p{index:04d}"
        for index, item in enumerate(triples, start=1):
            item["id"] = f"{label}-t{index:04d}"
        for index, item in enumerate(whole, start=1):
            item["id"] = f"{label}-w{index:04d}"
        payload[label] = {
            **stay,
            "filters": {
                "max_resort_km": args.max_resort_km,
                "max_unit_km": args.max_unit_km,
                "allow_unknown_distance": args.allow_unknown_distance,
            },
            "pairs": pairs,
            "triples": triples,
            "whole": whole,
        }
        (out_dir / f"combos_{label}.json").write_text(
            json.dumps(payload[label], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n#### {label} ({stay['check_in']} – {stay['check_out']})")
        print(
            f"Filtr: do {args.max_resort_km:g} km od střediska, jednotky od sebe "
            f"do {args.max_unit_km:g} km"
            + ("" if args.allow_unknown_distance else ", jen známé vzdálenosti")
        )
        print(f"Dvojice: {len(pairs)}, trojice: {len(triples)}, celé objekty: {len(whole)}")
        areas = sorted({item["area"] for item in pairs} | {item["area"] for item in whole})
        for area in areas:
            area_pairs = [item for item in pairs if item["area"] == area][:2]
            area_whole = [item for item in whole if item["area"] == area][:1]
            print(f"\n  {area}")
            for item in area_whole:
                unit = item["units"][0]
                distance = unit.get("resort_km")
                distance_text = f"{distance} km" if distance is not None else "? km"
                print(
                    f"    celý objekt: {item['total']:.0f} € ({item['per_person_night']:.1f} €/os/noc, "
                    f"{item['total_bedrooms']} ložnic, {distance_text}) – "
                    f"{unit['provider']} {unit['title']}"
                )
            for item in area_pairs:
                distance = "?" if item["max_unit_km"] is None else f"{item['max_unit_km']:.1f} km"
                same = " stejná budova," if item.get("same_building") else ""
                print(
                    f"    {item['split']}: {item['total']:.0f} € ({item['per_person_night']:.1f} €/os/noc, "
                    f"{same} odb. {distance}) – {format_units(item)}"
                )
    (out_dir / "combos.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nUloženo: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
