#!/usr/bin/env python3
from __future__ import annotations

import itertools
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "trip_search" / "cheap"
OUT = ROOT / "docs" / "data"

RESORTS = {
    "Tauplitz / Schneebären": {
        "color": "#2563eb",
        "points": [{"name": "Tauplitz", "lat": 47.5580, "lng": 14.0480}],
    },
    "Kreischberg + Lachtal": {
        "color": "#16a34a",
        "points": [
            {"name": "Kreischberg", "lat": 47.1170, "lng": 14.1830},
            {"name": "Lachtal", "lat": 47.2500, "lng": 14.2830},
        ],
    },
    "Dachstein West": {
        "color": "#d97706",
        "points": [
            {"name": "Gosau", "lat": 47.5840, "lng": 13.5350},
            {"name": "Annaberg", "lat": 47.5140, "lng": 13.4330},
            {"name": "Russbach", "lat": 47.5910, "lng": 13.4660},
        ],
    },
    "Schladming 4 Berge": {
        "color": "#dc2626",
        "points": [
            {"name": "Schladming", "lat": 47.3940, "lng": 13.6880},
            {"name": "Rohrmoos", "lat": 47.3830, "lng": 13.6830},
            {"name": "Pichl", "lat": 47.3860, "lng": 13.6130},
            {"name": "Haus im Ennstal", "lat": 47.4070, "lng": 13.7670},
        ],
    },
    "Katschberg – Aineck": {
        "color": "#7c3aed",
        "data_note": "Část Airbnb dat; trivago nabídky níže jsou orientační bez ověření ložnic.",
        "points": [
            {"name": "Katschberg", "lat": 47.0560, "lng": 13.6170},
            {"name": "Aineck", "lat": 47.0650, "lng": 13.6200},
        ],
    },
    "Obertauern": {
        "color": "#0891b2",
        "points": [{"name": "Obertauern", "lat": 47.2490, "lng": 13.5580}],
        "data_note": "Pro tento termín nejsou v datech páry 3BR/2BR do 3 500 €. Data se doplní po resetu API kvót.",
    },
    "Hochkönig": {
        "color": "#be123c",
        "data_note": "Část Airbnb dat; trivago nabídky níže jsou orientační bez ověření ložnic.",
        "points": [
            {"name": "Maria Alm", "lat": 47.4060, "lng": 12.9030},
            {"name": "Dienten", "lat": 47.3830, "lng": 12.9990},
            {"name": "Mühlbach", "lat": 47.3830, "lng": 13.0500},
        ],
    },
    "Nassfeld": {
        "color": "#65a30d",
        "data_note": "V hlavní párové sadě zatím nejsou 3BR/2BR data; trivago nabídky níže jsou orientační bez ověření ložnic.",
        "points": [
            {"name": "Nassfeld", "lat": 46.5660, "lng": 13.2760},
            {"name": "Hermagor", "lat": 46.6270, "lng": 13.3670},
        ],
    },
}

BOOKING_FILES = {
    "7": RAW / "booking_actor_schladming_7a_4n.json",
    "5": RAW / "booking_actor_schladming_5a_4n.json",
}

FILES = {
    "schladming": {
        "7": RAW / "airbnb_schladming_area_7a_4n.json",
        "5": RAW / "airbnb_schladming_area_5a_4n.json",
    },
    "murau": {
        "7": RAW / "airbnb_murau_area_7a_4n.json",
        "5": RAW / "airbnb_murau_area_5a_4n.json",
    },
}


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius = 6371.0088
    phi1 = math.radians(a[0])
    phi2 = math.radians(b[0])
    dphi = math.radians(b[0] - a[0])
    dlambda = math.radians(b[1] - a[1])
    x = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(math.sqrt(x))


def parse_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace("\xa0", " ").replace(" ", "").replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    return float(match.group(0)) if match else None


def parse_bedrooms(item: dict[str, Any]) -> int | None:
    sub = item.get("subDescription") or {}
    values = list(sub.get("items") or [])
    values.extend([sub.get("title") or "", item.get("title") or ""])
    for value in values:
        match = re.search(r"(\d+)\s+bedroom", str(value), re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def nearest_resort(lat: float, lng: float) -> tuple[str, dict[str, Any], float]:
    best: tuple[str, dict[str, Any], float] | None = None
    for name, resort in RESORTS.items():
        for point in resort["points"]:
            dist = distance_km((lat, lng), (point["lat"], point["lng"]))
            if best is None or dist < best[2]:
                best = (name, point, dist)
    assert best is not None
    return best


def parse_item(item: dict[str, Any], role: str) -> dict[str, Any] | None:
    if item.get("roomType") != "Entire home/apt":
        return None
    capacity = item.get("personCapacity") or 0
    bedrooms = parse_bedrooms(item)
    if capacity < int(role) or bedrooms is None or bedrooms < (3 if role == "7" else 2):
        return None
    coords = item.get("coordinates") or {}
    lat, lng = coords.get("latitude"), coords.get("longitude")
    if lat is None or lng is None:
        return None
    price = parse_price(item.get("price") or {})
    if price is None:
        return None
    resort_name, resort_point, resort_km = nearest_resort(lat, lng)
    if resort_km > 25:
        return None
    rating = item.get("rating") or {}
    return {
        "provider": "Airbnb",
        "role": role,
        "id": str(item.get("id")),
        "title": item.get("title") or "Bez názvu",
        "url": item.get("url"),
        "price": round(price, 2),
        "capacity": capacity,
        "bedrooms": bedrooms,
        "lat": lat,
        "lng": lng,
        "resort": resort_name,
        "resort_point": resort_point,
        "resort_km": round(resort_km, 2),
        "image": item.get("thumbnail"),
        "rating": rating.get("guestSatisfaction"),
        "reviews": rating.get("reviewsCount"),
        "location": item.get("location"),
        "type": item.get("propertyType") or (item.get("subDescription") or {}).get("title"),
    }


def load_items() -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {"7": {}, "5": {}}
    for area in FILES.values():
        for role, path in area.items():
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data:
                parsed = parse_item(item, role)
                if parsed is not None:
                    result[role][parsed["id"]] = parsed
    return result


def load_booking_units() -> dict[str, list[dict[str, Any]]]:
    blocked = []
    result: dict[str, list[dict[str, Any]]] = {"7": [], "5": []}
    for role, path in BOOKING_FILES.items():
        if not path.exists():
            continue
        if "murau" in path.name and "booking" in path.name:
            blocked.append(str(path))
        for item in json.loads(path.read_text(encoding="utf-8")):
            location = item.get("location") or {}
            lat, lng = location.get("lat"), location.get("lng")
            if lat is None or lng is None:
                continue
            lat, lng = float(lat), float(lng)
            resort_name, resort_point, resort_km = nearest_resort(lat, lng)
            if resort_km > 25:
                continue
            for room in item.get("rooms") or []:
                bedroom_names = set()
                for bed_type in room.get("bedTypes") or []:
                    room_name = str(bed_type.get("room") or "")
                    if re.search(r"bedroom", room_name, re.IGNORECASE):
                        bedroom_names.add(re.sub(r"\s+", " ", room_name.strip()))
                room_type = str(room.get("roomType") or "")
                bedrooms = len(bedroom_names)
                match = re.search(r"(\d+)\s*[- ]?bedroom", room_type, re.IGNORECASE)
                if match:
                    bedrooms = max(bedrooms, int(match.group(1)))
                for word, number in {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}.items():
                    if re.search(rf"\b{word}[- ]bedroom", room_type, re.IGNORECASE):
                        bedrooms = max(bedrooms, number)
                minimum = 3 if role == "7" else 2
                if bedrooms < minimum:
                    continue
                options = [
                    option
                    for option in (room.get("options") or [])
                    if (option.get("persons") or 0) >= int(role) and option.get("price")
                ]
                if not options:
                    continue
                best = min(options, key=lambda option: option["price"])
                result[role].append(
                    {
                        "provider": "Booking",
                        "role": role,
                        "id": f"booking-{item.get('hotelId')}-{room_type}-{len(result[role])}",
                        "title": f"{item.get('name')} · {room_type}",
                        "url": item.get("url"),
                        "price": float(best["price"]),
                        "capacity": best.get("persons") or room.get("persons"),
                        "bedrooms": bedrooms,
                        "lat": lat,
                        "lng": lng,
                        "resort": resort_name,
                        "resort_point": resort_point,
                        "resort_km": round(resort_km, 2),
                        "image": item.get("image"),
                        "rating": item.get("rating"),
                        "reviews": item.get("reviews"),
                        "location": (item.get("address") or {}).get("city")
                        or (item.get("address") or {}).get("full"),
                        "type": item.get("type"),
                    }
                )
    if blocked:
        print("Poznámka: Booking Murau nebyl použit (Apify limit).")
    return result


def build_mixed_pairs(
    items: dict[str, dict[str, dict[str, Any]]],
    booking: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for seven in list(items["7"].values()) + booking["7"]:
        for five in list(items["5"].values()) + booking["5"]:
            if seven["provider"] == five["provider"]:
                continue
            if seven["resort"] != five["resort"] or seven["id"] == five["id"]:
                continue
            total = seven["price"] + five["price"]
            if total > 3500:
                continue
            key = (seven["id"], five["id"])
            if key in seen:
                continue
            seen.add(key)
            unit_distance = distance_km((seven["lat"], seven["lng"]), (five["lat"], five["lng"]))
            pairs.append(
                {
                    "id": f"mix{len(pairs) + 1:03d}",
                    "resort": seven["resort"],
                    "provider": "Mix",
                    "total": round(total, 2),
                    "czk_per_person": round(total * 25 / 12),
                    "over_budget": total > 3000,
                    "nights": 4,
                    "check_in": "2027-01-30",
                    "check_out": "2027-02-03",
                    "distance_units_km": round(unit_distance, 2),
                    "max_resort_km": max(seven["resort_km"], five["resort_km"]),
                    "units": [seven, five],
                }
            )
    pairs.sort(key=lambda pair: (pair["total"], pair["max_resort_km"]))
    return pairs


PROVISIONAL_PREFIXES = {
    "Katschberg – Aineck": "katschberg",
    "Obertauern": "obertauern",
    "Hochkönig": "hochkönig",
    "Nassfeld": "nassfeld",
}


def build_provisional() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for resort_name, prefix in PROVISIONAL_PREFIXES.items():
        lists = {}
        for role in ("7", "5"):
            path = RAW.parent / "new_resorts" / f"trivago_{prefix}_{role}a.json"
            if not path.exists():
                lists[role] = []
                continue
            rows = []
            for item in json.loads(path.read_text(encoding="utf-8")):
                lat, lng = item.get("latitude"), item.get("longitude")
                if lat is None or lng is None:
                    continue
                lat, lng = float(lat), float(lng)
                nearest_name, nearest_point, nearest_km = nearest_resort(lat, lng)
                if nearest_name != resort_name or nearest_km > 25:
                    continue
                deal = (item.get("deals") or [{}])[0]
                price = parse_price(deal.get("price_per_stay"))
                if price is None:
                    continue
                rows.append(
                    {
                        "provider": "Trivago",
                        "role": role,
                        "name": item.get("accommodation_name"),
                        "price": price,
                        "lat": lat,
                        "lng": lng,
                        "resort": resort_name,
                        "resort_point": nearest_point,
                        "resort_km": round(nearest_km, 2),
                        "url": deal.get("deal_url"),
                        "note": "ložnice neověřené",
                    }
                )
            rows.sort(key=lambda row: row["price"])
            lists[role] = rows
        pairs = []
        for seven in lists["7"][:30]:
            for five in lists["5"][:40]:
                if seven["name"] == five["name"]:
                    continue
                total = seven["price"] + five["price"]
                if total > 3500:
                    continue
                pairs.append(
                    {
                        "area": resort_name,
                        "total": round(total, 2),
                        "units": [seven, five],
                        "note": "Orientační ceny z trivaga; počty ložnic nejsou ověřené.",
                    }
                )
        pairs.sort(key=lambda pair: pair["total"])
        result.extend(pairs[:3])
    return result


LOCAL_AIRBNB = RAW.parent / "local_airbnb"
LOCAL_ROLE_BEDROOMS = {2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 4, 9: 4, 10: 4}
MULTI_PATTERNS = [
    (8, 4),
    (6, 6),
    (9, 3),
    (10, 2),
    (4, 4, 4),
    (5, 4, 3),
    (6, 3, 3),
    (5, 5, 2),
    (7, 3, 2),
    (6, 4, 2),
    (8, 2, 2),
    (3, 3, 3, 3),
]


def load_local_airbnb_units() -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {"7": {}, "5": {}}
    if not LOCAL_AIRBNB.exists():
        return result
    for path in sorted(LOCAL_AIRBNB.glob("*_7.json")) + sorted(LOCAL_AIRBNB.glob("*_5.json")):
        role = "7" if path.stem.endswith("_7") else "5"
        for item in json.loads(path.read_text(encoding="utf-8")):
            title = str(item.get("title") or "")
            if title.lower().startswith("room in"):
                continue
            bedrooms = None
            for line in ((item.get("structuredContent") or {}).get("primaryLine") or []):
                match = re.search(r"(\d+)\s+bedroom", str(line.get("body") or ""), re.IGNORECASE)
                if match:
                    bedrooms = int(match.group(1))
                    break
            if bedrooms is None or bedrooms < (3 if role == "7" else 2):
                continue
            coords = item.get("coordinates") or {}
            lat, lng = coords.get("latitude"), coords.get("longitud") or coords.get("longitude")
            if lat is None or lng is None:
                continue
            price = ((item.get("price") or {}).get("unit") or {}).get("amount")
            if not price:
                for part in (item.get("price") or {}).get("break_down") or []:
                    if "total" in str(part.get("description") or "").lower():
                        price = part.get("amount")
                        break
            if not price:
                continue
            resort_name, resort_point, resort_km = nearest_resort(float(lat), float(lng))
            if resort_km > 25:
                continue
            rating = item.get("rating") or {}
            result[role][str(item.get("room_id"))] = {
                "provider": "Airbnb",
                "role": role,
                "id": str(item.get("room_id")),
                "title": item.get("name") or title,
                "url": f"https://www.airbnb.com/rooms/{item.get('room_id')}",
                "price": float(price),
                "capacity": int(role),
                "bedrooms": bedrooms,
                "lat": float(lat),
                "lng": float(lng),
                "resort": resort_name,
                "resort_point": resort_point,
                "resort_km": round(resort_km, 2),
                "image": ((item.get("images") or [{}])[0]).get("url"),
                "rating": rating.get("value"),
                "reviews": rating.get("reviewCount"),
                "location": title,
                "type": "Airbnb (local)",
            }
    return result


LOCAL_BOOKING = RAW.parent / "local_booking"
pairs_all: list[dict[str, Any]] = []
multi_pairs_all: list[dict[str, Any]] = []

LOCAL_BOOKING_AREAS = {
    "katschberg": "Katschberg – Aineck",
    "obertauern": "Obertauern",
    "hochkoenig": "Hochkönig",
    "nassfeld": "Nassfeld",
}


def parse_local_airbnb_unit(item: dict[str, Any], role: int) -> dict[str, Any] | None:
    title = str(item.get("title") or "")
    if title.lower().startswith("room in"):
        return None
    bedrooms = None
    for line in ((item.get("structuredContent") or {}).get("primaryLine") or []):
        match = re.search(r"(\d+)\s+bedroom", str(line.get("body") or ""), re.IGNORECASE)
        if match:
            bedrooms = int(match.group(1))
            break
    if bedrooms is None or bedrooms < LOCAL_ROLE_BEDROOMS[role]:
        return None
    coords = item.get("coordinates") or {}
    lat, lng = coords.get("latitude"), coords.get("longitud") or coords.get("longitude")
    if lat is None or lng is None:
        return None
    price = ((item.get("price") or {}).get("unit") or {}).get("amount")
    if not price:
        for part in (item.get("price") or {}).get("break_down") or []:
            if "total" in str(part.get("description") or "").lower():
                price = part.get("amount")
                break
    if not price:
        return None
    resort_name, resort_point, resort_km = nearest_resort(float(lat), float(lng))
    if resort_km > 25:
        return None
    rating = item.get("rating") or {}
    return {
        "provider": "Airbnb",
        "role": str(role),
        "id": str(item.get("room_id")),
        "title": item.get("name") or title,
        "url": f"https://www.airbnb.com/rooms/{item.get('room_id')}",
        "price": float(price),
        "capacity": role,
        "bedrooms": bedrooms,
        "lat": float(lat),
        "lng": float(lng),
        "resort": resort_name,
        "resort_point": resort_point,
        "resort_km": round(resort_km, 2),
        "image": ((item.get("images") or [{}])[0]).get("url"),
        "rating": rating.get("value"),
        "reviews": rating.get("reviewCount"),
        "location": title,
        "type": "Airbnb (local)",
    }


def load_local_booking_units() -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for key, area_name in LOCAL_BOOKING_AREAS.items():
        result[area_name] = {}
        for role in LOCAL_ROLE_BEDROOMS:
            path = LOCAL_BOOKING / f"{key}_{role}.json"
            if not path.exists():
                continue
            report = json.loads(path.read_text(encoding="utf-8"))
            query = (report.get("queries") or [{}])[0]
            rows = []
            for offer in query.get("offers") or []:
                bedrooms = offer.get("bedrooms") or 0
                if bedrooms < LOCAL_ROLE_BEDROOMS[role]:
                    continue
                price = offer.get("total_price")
                if not price:
                    continue
                title = offer.get("title") or "Booking"
                url = offer.get("link")
                if not url:
                    continue
                rows.append(
                    {
                        "provider": "Booking",
                        "role": str(role),
                        "id": f"booking:{url}:{title}:{role}",
                        "title": title,
                        "url": url,
                        "price": float(price),
                        "capacity": role,
                        "bedrooms": bedrooms,
                        "lat": None,
                        "lng": None,
                        "resort": area_name,
                        "resort_point": RESORTS[area_name]["points"][0],
                        "resort_km": None,
                        "image": None,
                        "rating": offer.get("rating_score"),
                        "reviews": offer.get("review_count"),
                        "location": offer.get("address"),
                        "type": "Booking local",
                    }
                )
            unique = {unit["url"] + unit["title"]: unit for unit in rows}
            result[area_name][str(role)] = sorted(unique.values(), key=lambda unit: unit["price"])[:6]
    return result


def build_multi_pairs() -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for role in LOCAL_ROLE_BEDROOMS:
        path = LOCAL_AIRBNB / f"PLACEHOLDER_{role}.json"
        for file_path in LOCAL_AIRBNB.glob(f"*_{role}.json"):
            for item in json.loads(file_path.read_text(encoding="utf-8")):
                unit = parse_local_airbnb_unit(item, role)
                if unit is None:
                    continue
                grouped.setdefault(unit["resort"], {}).setdefault(str(role), []).append(unit)
    for resort in grouped:
        for role in grouped[resort]:
            unique = {unit["id"]: unit for unit in grouped[resort][role]}
            grouped[resort][role] = sorted(unique.values(), key=lambda unit: unit["price"])[:8]

    result: list[dict[str, Any]] = []
    booking_grouped = load_local_booking_units()
    for resort in RESORTS:
        air_by_role = grouped.get(resort, {})
        book_by_role = booking_grouped.get(resort, {})
        for pattern in MULTI_PATTERNS:
            role_lists = []
            for role in pattern:
                key = str(role)
                air_units = air_by_role.get(key, [])[:6]
                book_units = book_by_role.get(key, [])[:6]
                if not air_units and not book_units:
                    break
                role_lists.append(air_units + book_units)
            else:
                combos = []
                for combo in itertools.product(*role_lists):
                    if len({unit["id"] for unit in combo}) < len(combo):
                        continue
                    total = sum(unit["price"] for unit in combo)
                    if total > 3500:
                        continue
                    total_bedrooms = sum(unit["bedrooms"] for unit in combo)
                    if total_bedrooms < 5:
                        continue
                    if all(unit.get("lat") is not None and unit.get("lng") is not None for unit in combo):
                        distances = []
                        for index, left in enumerate(combo):
                            for right in combo[index + 1 :]:
                                distances.append(
                                    distance_km(
                                        (left["lat"], left["lng"]),
                                        (right["lat"], right["lng"]),
                                    )
                                )
                        max_unit_km = round(max(distances), 2) if distances else 0.0
                    else:
                        max_unit_km = None
                    resort_kms = [unit.get("resort_km") for unit in combo]
                    max_resort_km = round(max(resort_kms), 2) if all(value is not None for value in resort_kms) else None
                    providers = {unit["provider"] for unit in combo}
                    provider = "Airbnb" if providers == {"Airbnb"} else "Booking" if providers == {"Booking"} else "Mix"
                    combos.append(
                        {
                            "area": resort,
                            "split": "+".join(str(role) for role in pattern),
                            "provider": provider,
                            "total": round(total, 2),
                            "czk_per_person": round(total * 25 / 12),
                            "total_bedrooms": total_bedrooms,
                            "max_resort_km": max_resort_km,
                            "max_unit_km": max_unit_km,
                            "units": list(combo),
                            "note": "Lokální Airbnb/Booking; vzdálenosti vzdušnou čarou, u Booking mohou chybět.",
                        }
                    )
            combos.sort(key=lambda combo: combo["total"])
            result.extend(combos[:2])
    result.sort(key=lambda combo: (combo["area"], combo["total"]))
    for index, combo in enumerate(result, start=1):
        combo["id"] = f"m{index:03d}"
    return result


def build_unified_options(
    pairs: list[dict[str, Any]],
    multi: list[dict[str, Any]],
    booking_local: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for item in pairs:
        raw.append(
            {
                **item,
                "area": item["resort"],
                "split": "+".join(unit["role"] for unit in item["units"]),
                "max_unit_km": item.get("distance_units_km"),
            }
        )
    raw.extend(multi)
    for item in booking_local:
        raw.append(
            {
                **item,
                "resort": item["area"],
                "split": "+".join(unit["role"] for unit in item["units"]),
                "max_unit_km": None,
                "max_resort_km": None,
            }
        )

    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    for item in raw:
        units = item.get("units") or []
        if not units:
            continue
        area = item.get("area") or item.get("resort")
        if not area:
            continue
        areas = {unit.get("resort") or area for unit in units}
        area = item.get("resort") or item.get("area") or next(iter(areas))
        point = RESORTS.get(area, {}).get("points", [{}])[0]
        for unit in units:
            unit.setdefault("id", f"booking:{unit.get('url')}:{unit.get('title')}:{unit.get('role')}")
            unit.setdefault("resort", area)
            unit.setdefault("resort_point", point)
            unit.setdefault("provider", item.get("provider", "Airbnb"))
        providers = {unit.get("provider", "Airbnb") for unit in units}
        provider = "Airbnb" if providers == {"Airbnb"} else "Booking" if providers == {"Booking"} else "Mix"
        split = item.get("split") or "+".join(unit["role"] for unit in units)
        total = item["total"]
        max_resort = item.get("max_resort_km")
        max_unit = item.get("max_unit_km", item.get("distance_units_km"))
        key = tuple(sorted(unit["id"] for unit in units))
        if key in by_key and by_key[key]["total"] <= total:
            continue
        by_key[key] = {
            "id": "",
            "area": area,
            "split": split,
            "provider": provider,
            "total": total,
            "czk_per_person": item.get("czk_per_person", round(total * 25 / 12)),
            "total_bedrooms": sum(unit["bedrooms"] for unit in units),
            "max_resort_km": max_resort,
            "max_unit_km": max_unit,
            "check_in": item.get("check_in", "2027-01-30"),
            "check_out": item.get("check_out", "2027-02-03"),
            "nights": 4,
            "units": units,
            "score": total
            + (max_resort if max_resort is not None else 25) * 25
            + (max_unit if max_unit is not None else 25) * 5,
        }
    result = list(by_key.values())
    result.sort(key=lambda option: option["score"])
    for index, option in enumerate(result, start=1):
        option["id"] = f"o{index:04d}"
    return result


def build_best_options() -> list[dict[str, Any]]:
    def option_score(item: dict[str, Any]) -> float:
        unit_distance = item.get("max_unit_km", item.get("distance_units_km"))
        if unit_distance is None:
            unit_distance = 25
        resort_distance = item.get("max_resort_km")
        if resort_distance is None:
            resort_distance = 25
        return item["total"] + resort_distance * 25 + unit_distance * 5

    result = []
    for resort in RESORTS:
        twos = [
            item
            for item in pairs_all
            if item.get("resort") == resort and len(item.get("units", [])) == 2
        ]
        twos += [
            item
            for item in multi_pairs_all
            if item.get("area") == resort and len(item.get("units", [])) == 2
        ]
        multis = [
            item
            for item in multi_pairs_all
            if item.get("area") == resort and len(item.get("units", [])) >= 3
        ]
        best_two = min(twos, key=option_score) if twos else None
        best_multi = min(multis, key=option_score) if multis else None
        def compact(item: dict[str, Any] | None) -> dict[str, Any] | None:
            if item is None:
                return None
            return {
                "split": item.get("split") or "+".join(unit["role"] for unit in item["units"]),
                "total": item["total"],
                "czk_per_person": item["czk_per_person"],
                "max_resort_km": item["max_resort_km"],
                "max_unit_km": item.get("max_unit_km", item.get("distance_units_km", 0)),
                "units": item["units"],
                "over_budget": item["total"] > 3000,
            }
        result.append(
            {
                "resort": resort,
                "best_two": compact(best_two),
                "best_multi": compact(best_multi),
            }
        )
    return result


def build_local_booking_pairs() -> list[dict[str, Any]]:
    units_by_area: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for key, area_name in LOCAL_BOOKING_AREAS.items():
        units_by_area[area_name] = {"7": [], "5": []}
        for role in ("7", "5"):
            path = LOCAL_BOOKING / f"{key}_{role}.json"
            if not path.exists():
                continue
            report = json.loads(path.read_text(encoding="utf-8"))
            query = (report.get("queries") or [{}])[0]
            for offer in query.get("offers") or []:
                bedrooms = offer.get("bedrooms") or 0
                if bedrooms < (3 if role == "7" else 2):
                    continue
                price = offer.get("total_price")
                if not price:
                    continue
                units_by_area[area_name][role].append(
                    {
                        "provider": "Booking",
                        "role": role,
                        "title": offer.get("title"),
                        "price": float(price),
                        "bedrooms": bedrooms,
                        "url": offer.get("link"),
                        "address": offer.get("address"),
                        "rating": offer.get("rating_score"),
                        "reviews": offer.get("review_count"),
                        "note": "Booking lokálně, vzdálenost neuvedena",
                    }
                )
    result: list[dict[str, Any]] = []
    for area_name, lists in units_by_area.items():
        pairs = []
        for seven in lists["7"]:
            for five in lists["5"]:
                if seven.get("url") == five.get("url"):
                    continue
                total = seven["price"] + five["price"]
                if total > 3500:
                    continue
                pairs.append(
                    {
                        "area": area_name,
                        "total": round(total, 2),
                        "units": [seven, five],
                        "note": "Booking lokálně; vzdálenost mezi objektem a areálem není v datech.",
                    }
                )
        pairs.sort(key=lambda pair: pair["total"])
        result.extend(pairs[:5])
    return result


def booking_park_pair() -> dict[str, Any]:
    lat, lng = 47.10928845876713, 14.16832621686473
    resort_name, resort_point, resort_km = nearest_resort(lat, lng)
    base = {
        "provider": "Booking",
        "role": "7",
        "id": "booking-park-3br",
        "title": "Park apartman Murau: Three-Bedroom Apartment",
        "url": "https://www.booking.com/hotel/at/park-apartmanhaz.html",
        "price": 1033.0,
        "capacity": 8,
        "bedrooms": 3,
        "lat": lat,
        "lng": lng,
        "resort": resort_name,
        "resort_point": resort_point,
        "resort_km": round(resort_km, 2),
        "image": None,
        "rating": None,
        "reviews": None,
        "location": "Murau",
        "type": "Booking apartment",
    }
    five = dict(base)
    five.update(
        {
            "role": "5",
            "id": "booking-park-3br-suite",
            "title": "Park apartman Murau: Three-Bedroom Suite",
            "price": 1104.0,
        }
    )
    total = 3432.0
    return {
        "id": "booking-park",
        "resort": resort_name,
        "provider": "Booking",
        "total": total,
        "czk_per_person": round(total * 25 / 12),
        "over_budget": total > 3000,
        "nights": 4,
        "check_in": "2027-01-31",
        "check_out": "2027-02-04",
        "distance_units_km": 0.0,
        "max_resort_km": max(base["resort_km"], five["resort_km"]),
        "units": [base, five],
    }


def build_pairs(items: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for seven in items["7"].values():
        for five in items["5"].values():
            if seven["resort"] != five["resort"] or seven["id"] == five["id"]:
                continue
            key = (seven["id"], five["id"])
            if key in seen:
                continue
            total = seven["price"] + five["price"]
            if total > 3500:
                continue
            seen.add(key)
            unit_distance = distance_km((seven["lat"], seven["lng"]), (five["lat"], five["lng"]))
            pairs.append(
                {
                    "id": f"p{len(pairs) + 1:03d}",
                    "resort": seven["resort"],
                    "provider": "Airbnb",
                    "total": round(total, 2),
                    "czk_per_person": round(total * 25 / 12),
                    "over_budget": total > 3000,
                    "nights": 4,
                    "check_in": "2027-01-30",
                    "check_out": "2027-02-03",
                    "distance_units_km": round(unit_distance, 2),
                    "max_resort_km": max(seven["resort_km"], five["resort_km"]),
                    "units": [seven, five],
                }
            )
    pairs.append(booking_park_pair())
    pairs.sort(key=lambda p: (p["total"], p["max_resort_km"], p["distance_units_km"]))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for pair in pairs:
        grouped.setdefault(pair["resort"], []).append(pair)
    selected: list[dict[str, Any]] = []
    for resort in RESORTS:
        selected.extend(grouped.get(resort, [])[:30])
    for pair in pairs:
        if pair["provider"] == "Booking" and pair not in selected:
            selected.append(pair)
    booking_units = load_booking_units()
    for pair in build_mixed_pairs(items, booking_units):
        if pair not in selected:
            selected.append(pair)
    selected.sort(key=lambda p: (p["resort"], p["total"]))
    for index, pair in enumerate(selected, start=1):
        pair["id"] = f"p{index:03d}"
    return selected


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    items = load_items()
    local = load_local_airbnb_units()
    for role in ("7", "5"):
        items[role].update(local[role])
    pairs = build_pairs(items)
    global pairs_all, multi_pairs_all
    pairs_all = pairs
    multi_pairs_all = build_multi_pairs()
    booking_local_all = build_local_booking_pairs()
    unified_options = build_unified_options(pairs, multi_pairs_all, booking_local_all)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "assumptions": {
            "check_in": "2027-01-30",
            "check_out": "2027-02-03",
            "nights": 4,
            "adults": 12,
            "split": "7 + 5",
            "bedrooms": {"7": "min. 3", "5": "min. 2"},
            "price_note": "Airbnb total a Booking search cena + daně za 4 noci.",
            "distance_note": "Vzdálenosti jsou vzdušnou čarou, ne doba jízdy.",
            "budget_total": 3000,
            "budget_czk_per_person": 5000,
            "czk_per_eur": 25,
        },
        "resorts": RESORTS,
        "pairs": pairs,
        "provisional": build_provisional(),
        "booking_local": booking_local_all,
        "multi_pairs": multi_pairs_all,
        "best_options": build_best_options(),
        "options": unified_options,
    }
    (OUT / "pairs.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "pairs.js").write_text(
        "window.PAIR_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"Páry: {len(pairs)}")
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair["resort"]] = counts.get(pair["resort"], 0) + 1
    for resort, count in counts.items():
        print(f"  {resort}: {count}")
    print(f"Zapsáno: {OUT / 'pairs.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
