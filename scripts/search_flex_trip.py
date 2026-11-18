#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from search_ski_resorts import (
    BASES,
    call_searchapi,
    distance_km,
    parse_bedrooms,
    parse_price,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hory.staying import load_dotenv


def allowed_date(value: str | None) -> bool:
    return value in {"2027-01-29", "2027-01-30", "2027-01-31", "2027-02-01"}


def booking_candidates(
    body: dict[str, Any],
    center: tuple[float, float],
    radius_km: float,
    *,
    nights: int,
) -> list[dict[str, Any]]:
    result = []
    for prop in body.get("properties") or []:
        if prop.get("nights") != nights:
            continue
        if not allowed_date(prop.get("check_in_date")):
            continue
        location = prop.get("gps_coordinates") or {}
        lat, lng = location.get("latitude"), location.get("longitude")
        if lat is None or lng is None:
            continue
        distance = distance_km(center[0], center[1], lat, lng)
        if distance > radius_km:
            continue
        title = str(prop.get("title") or "")
        room_type = str(prop.get("room_type") or "")
        text = f"{title} {room_type}".lower()
        bedrooms = prop.get("bedrooms")
        try:
            bedrooms_value = int(bedrooms) if bedrooms is not None else 0
        except (TypeError, ValueError):
            bedrooms_value = 0
        whole_signal = any(
            word in text
            for word in (
                "house",
                "chalet",
                "villa",
                "vacation home",
                "ferienhaus",
                "hütte",
                "huette",
                "resort",
                "aparthotel",
            )
        )
        apartment_signal = "apartment" in text or "apartm" in text
        if not (whole_signal or apartment_signal or bedrooms_value >= 3):
            continue
        result.append(
            {
                "source": "Booking",
                "name": title,
                "url": prop.get("link"),
                "distance_km": round(distance, 2),
                "date": (prop.get("check_in_date"), prop.get("check_out_date")),
                "nights": nights,
                "bedrooms": bedrooms,
                "beds": prop.get("beds"),
                "bathrooms": prop.get("bathrooms"),
                "room_type": room_type,
                "price": parse_price(prop.get("extracted_price") or prop.get("price")),
                "currency": prop.get("currency") or "EUR",
                "search_price_text": prop.get("price"),
                "taxes_text": prop.get("taxes_and_charges"),
                "priority": 0 if whole_signal else 1 if bedrooms_value >= 3 else 2,
                "raw_property": prop,
            }
        )
    result.sort(key=lambda item: (item["priority"], item["price"] or 1e12))
    return result


def airbnb_candidates(
    body: dict[str, Any],
    center: tuple[float, float],
    radius_km: float,
    *,
    date: tuple[str, str],
    nights: int,
) -> list[dict[str, Any]]:
    result = []
    for prop in body.get("properties") or []:
        location = prop.get("gps_coordinates") or {}
        lat, lng = location.get("latitude"), location.get("longitude")
        if lat is None or lng is None:
            continue
        distance = distance_km(center[0], center[1], lat, lng)
        if distance > radius_km:
            continue
        bedrooms = parse_bedrooms(prop.get("accommodations"))
        if bedrooms is not None and bedrooms < 3:
            continue
        price = prop.get("price") or {}
        total = parse_price(price.get("extracted_total_price") or price.get("total_price"))
        result.append(
            {
                "source": "Airbnb",
                "name": prop.get("title"),
                "url": prop.get("link"),
                "distance_km": round(distance, 2),
                "date": date,
                "nights": nights,
                "bedrooms": bedrooms,
                "price": total,
                "currency": price.get("currency") or "EUR",
                "search_price_text": price.get("total_price"),
                "priority": 0 if (bedrooms or 0) >= 4 else 1,
                "raw_property": prop,
            }
        )
    result.sort(key=lambda item: (item["priority"], item["price"] or 1e12))
    return result


def booking_detail(
    key: str,
    candidate: dict[str, Any],
    args: argparse.Namespace,
    raw_path: Path,
) -> dict[str, Any]:
    check_in, check_out = candidate["date"]
    body = call_searchapi(
        key,
        {
            "engine": "booking_property",
            "url": candidate["raw_property"].get("link"),
            "check_in_date": check_in,
            "check_out_date": check_out,
            "adults": args.adults,
            "children_ages": args.child_ages,
            "rooms": 1,
            "currency": args.currency,
            "language": "en-us",
        },
        raw_path,
    )
    info = body.get("property_information") or {}
    rooms = body.get("rooms") or []
    unit_by_name: dict[str, dict[str, Any]] = {}
    for room in rooms:
        name = str(room.get("name") or "")
        max_guests = room.get("max_guests")
        try:
            max_guests_value = int(max_guests) if max_guests is not None else 0
        except (TypeError, ValueError):
            max_guests_value = 0
        price = parse_price(room.get("price"))
        if max_guests_value <= 0 or price is None:
            continue
        unit = {
            "name": name,
            "max_guests": max_guests_value,
            "price": price,
            "price_text": room.get("price"),
            "currency": room.get("currency"),
            "bed_configuration": room.get("bed_configuration"),
        }
        existing = unit_by_name.get(name)
        if existing is None or price < (existing.get("price") or 1e12):
            unit_by_name[name] = unit

    units = list(unit_by_name.values())
    whole = [unit for unit in units if unit["max_guests"] >= args.adults + len(args.child_ages)]
    whole.sort(key=lambda item: item["price"])
    combos = []
    for size in (2, 3):
        for combo in itertools.combinations(units, size):
            capacity = sum(unit["max_guests"] for unit in combo)
            if capacity < args.adults + len(args.child_ages):
                continue
            total = sum(unit["price"] for unit in combo)
            combos.append({"units": list(combo), "capacity": capacity, "price": total})
    combos.sort(key=lambda item: item["price"])
    return {
        **candidate,
        "property_type": info.get("property_type"),
        "property_name": info.get("name"),
        "city": info.get("city"),
        "best_whole": whole[0] if whole else None,
        "best_combo": combos[0] if combos else None,
        "unit_count": len(units),
        "units": units[:12],
    }


def airbnb_detail(
    key: str,
    candidate: dict[str, Any],
    args: argparse.Namespace,
    raw_path: Path,
) -> dict[str, Any]:
    check_in, check_out = candidate["date"]
    body = call_searchapi(
        key,
        {
            "engine": "airbnb_property",
            "property_id": candidate["raw_property"].get("id"),
            "check_in_date": check_in,
            "check_out_date": check_out,
            "adults": args.adults,
            "children": len(args.child_ages),
            "currency": args.currency,
        },
        raw_path,
    )
    prop = body.get("property") or {}
    price = prop.get("price") or {}
    return {
        **candidate,
        "name": prop.get("title") or candidate["name"],
        "property_type": ", ".join(prop.get("accomodations") or []),
        "guest_capacity": prop.get("guest_capacity"),
        "bedrooms": prop.get("bedrooms") or candidate.get("bedrooms"),
        "price": parse_price(price.get("extracted_total_price") or price.get("total_price")),
        "price_text": price.get("total_price"),
        "taxes_text": price.get("taxes"),
        "currency": price.get("currency") or candidate["currency"],
    }


def format_price(value: float | None, currency: str = "EUR") -> str:
    return "—" if value is None else f"{value:,.0f} {currency}".replace(",", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Flexible ski accommodation search via SearchAPI.")
    parser.add_argument("--adults", type=int, default=12)
    parser.add_argument("--child-ages", default="6,9,12")
    parser.add_argument("--currency", default="EUR")
    parser.add_argument("--out", default="data/trip_search/flex_2027-01-30")
    args = parser.parse_args()
    args.child_ages = [age.strip() for age in args.child_ages.split(",") if age.strip()]
    load_dotenv()
    key = os.environ.get("SEARCHAPI_KEY", "").strip()
    if not key:
        print("Chybí SEARCHAPI_KEY v .env")
        return 2
    run_dir = Path(args.out)
    run_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for base_key, base in BASES.items():
        print(f"\n### {base['name']}")
        booking_5_body = call_searchapi(
            key,
            {
                "engine": "booking",
                "q": base["query"],
                "check_in_date": "2027-01-30",
                "check_out_date": "2027-02-04",
                "flex_window": 3,
                "adults": args.adults,
                "children_ages": ",".join(args.child_ages),
                "rooms": 1,
                "currency": args.currency,
                "page": 1,
            },
            run_dir / f"{base_key}_booking_5n_flex.json",
        )
        booking_4_body = call_searchapi(
            key,
            {
                "engine": "booking",
                "q": base["query"],
                "check_in_date": "2027-01-30",
                "check_out_date": "2027-02-03",
                "flex_window": 3,
                "adults": args.adults,
                "children_ages": ",".join(args.child_ages),
                "rooms": 1,
                "currency": args.currency,
                "page": 1,
            },
            run_dir / f"{base_key}_booking_4n_flex.json",
        )
        airbnb_5_body = call_searchapi(
            key,
            {
                "engine": "airbnb",
                "q": base["query"],
                "check_in_date": "2027-01-30",
                "check_out_date": "2027-02-04",
                "adults": args.adults,
                "children": len(args.child_ages),
                "currency": args.currency,
            },
            run_dir / f"{base_key}_airbnb_5n.json",
        )
        airbnb_4_body = call_searchapi(
            key,
            {
                "engine": "airbnb",
                "q": base["query"],
                "check_in_date": "2027-01-31",
                "check_out_date": "2027-02-04",
                "adults": args.adults,
                "children": len(args.child_ages),
                "currency": args.currency,
            },
            run_dir / f"{base_key}_airbnb_4n.json",
        )

        booking = booking_candidates(booking_5_body, base["center"], base["radius_km"], nights=5)
        booking += booking_candidates(booking_4_body, base["center"], base["radius_km"], nights=4)
        by_id = {}
        for item in booking:
            pid = str(item["raw_property"].get("property_id"))
            existing = by_id.get(pid)
            if existing is None or (item["price"] or 1e12) < (existing["price"] or 1e12):
                by_id[pid] = item
        booking = sorted(by_id.values(), key=lambda item: (item["priority"], item["price"] or 1e12))
        airbnb = airbnb_candidates(airbnb_5_body, base["center"], base["radius_km"], date=("2027-01-30", "2027-02-04"), nights=5)
        airbnb += airbnb_candidates(airbnb_4_body, base["center"], base["radius_km"], date=("2027-01-31", "2027-02-04"), nights=4)
        airbnb_by_id = {}
        for item in airbnb:
            aid = str(item["raw_property"].get("id"))
            existing = airbnb_by_id.get(aid)
            if existing is None or (item["price"] or 1e12) < (existing["price"] or 1e12):
                airbnb_by_id[aid] = item
        airbnb = sorted(airbnb_by_id.values(), key=lambda item: (item["priority"], item["price"] or 1e12))

        print(
            f"Booking: 5n flex {len(booking_5_body.get('properties') or [])}, "
            f"4n flex {len(booking_4_body.get('properties') or [])}, "
            f"kandidátů {len(booking)}"
        )
        print(
            f"Airbnb: 5n {len(airbnb_5_body.get('properties') or [])}, "
            f"4n {len(airbnb_4_body.get('properties') or [])}, "
            f"kandidátů {len(airbnb)}"
        )

        for index, candidate in enumerate(booking[:2], start=1):
            detail = booking_detail(key, candidate, args, run_dir / f"{base_key}_booking_detail_{index}.json")
            results.append({"base": base["name"], "base_key": base_key, **detail})
        for index, candidate in enumerate(airbnb[:2], start=1):
            detail = airbnb_detail(key, candidate, args, run_dir / f"{base_key}_airbnb_detail_{index}.json")
            results.append({"base": base["name"], "base_key": base_key, **detail})

    (run_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in results:
        if item["source"] == "Booking":
            best = item.get("best_whole") or item.get("best_combo")
            price = (best or {}).get("price") or item.get("price")
            cap = (best or {}).get("capacity") or (best or {}).get("max_guests")
            print(
                f"{item['base']} | Booking | {item.get('property_name')} | {item['date'][0]}–{item['date'][1]} | "
                f"cap {cap} | {format_price(price, item.get('currency') or 'EUR')} | {item['distance_km']} km"
            )
        else:
            print(
                f"{item['base']} | Airbnb | {item.get('name')} | {item['date'][0]}–{item['date'][1]} | "
                f"cap {item.get('guest_capacity')} | {format_price(item.get('price'), item.get('currency') or 'EUR')} | {item['distance_km']} km"
            )
    print(f"\nUloženo: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
