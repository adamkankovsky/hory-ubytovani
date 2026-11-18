#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any
import sys

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hory.staying import load_dotenv

SEARCHAPI_URL = "https://www.searchapi.io/api/v1/search"

BASES = {
    "tauplitz": {
        "name": "Tauplitz / Schneebären",
        "query": "Bad Mitterndorf, Austria",
        "center": (47.5550, 14.0830),
        "radius_km": 20.0,
    },
    "kreischberg": {
        "name": "Kreischberg + Lachtal",
        "query": "Murau, Austria",
        "center": (47.1110, 14.1690),
        "radius_km": 25.0,
    },
    "dachstein_west": {
        "name": "Dachstein West / Gosau",
        "query": "Gosau, Austria",
        "center": (47.5840, 13.5350),
        "radius_km": 20.0,
    },
    "schladming": {
        "name": "Schladming – 4 Berge",
        "query": "Schladming, Austria",
        "center": (47.3940, 13.6880),
        "radius_km": 20.0,
    },
}


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(math.sqrt(a))


def parse_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    digits = re.sub(r"[^0-9]", "", str(value))
    return float(digits) if digits else None


def parse_bedrooms(accommodations: Any) -> int | None:
    if not isinstance(accommodations, list):
        return None
    for item in accommodations:
        match = re.search(r"(\d+)\s+bedroom", str(item), re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def call_searchapi(key: str, params: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    request_params = dict(params, api_key=key)
    response = requests.get(SEARCHAPI_URL, params=request_params, timeout=180)
    body = response.json()
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    if response.status_code != 200:
        raise RuntimeError(
            f"SearchAPI {params.get('engine')} {params.get('q')}: "
            f"HTTP {response.status_code}: {json.dumps(body, ensure_ascii=False)[:500]}"
        )
    return body


def booking_candidates(
    body: dict[str, Any],
    center: tuple[float, float],
    radius_km: float,
) -> list[dict[str, Any]]:
    candidates = []
    for prop in body.get("properties") or []:
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
        priority = 0 if whole_signal else 1 if bedrooms_value >= 3 else 2
        candidates.append(
            {
                "source": "Booking",
                "name": title,
                "url": prop.get("link"),
                "distance_km": round(distance, 2),
                "bedrooms": bedrooms,
                "beds": prop.get("beds"),
                "bathrooms": prop.get("bathrooms"),
                "room_type": room_type,
                "price": parse_price(prop.get("extracted_price") or prop.get("price")),
                "currency": prop.get("currency") or "EUR",
                "search_price_text": prop.get("price"),
                "taxes_text": prop.get("taxes_and_charges"),
                "priority": priority,
                "raw_property": prop,
            }
        )
    candidates.sort(key=lambda item: (item["priority"], item["price"] or 1e12))
    return candidates


def airbnb_candidates(
    body: dict[str, Any],
    center: tuple[float, float],
    radius_km: float,
) -> list[dict[str, Any]]:
    candidates = []
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
        candidates.append(
            {
                "source": "Airbnb",
                "name": prop.get("title"),
                "url": prop.get("link"),
                "distance_km": round(distance, 2),
                "bedrooms": bedrooms,
                "beds": None,
                "bathrooms": None,
                "room_type": None,
                "price": total,
                "currency": price.get("currency") or "EUR",
                "search_price_text": price.get("total_price"),
                "taxes_text": None,
                "priority": 0 if (bedrooms or 0) >= 4 else 1,
                "raw_property": prop,
            }
        )
    candidates.sort(key=lambda item: (item["priority"], item["price"] or 1e12))
    return candidates


def booking_detail(
    key: str,
    candidate: dict[str, Any],
    args: argparse.Namespace,
    raw_path: Path,
) -> dict[str, Any]:
    body = call_searchapi(
        key,
        {
            "engine": "booking_property",
            "url": candidate["raw_property"].get("link"),
            "check_in_date": args.check_in,
            "check_out_date": args.check_out,
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
    whole_units = []
    small_units = []
    for room in rooms:
        max_guests = room.get("max_guests")
        try:
            max_guests_value = int(max_guests) if max_guests is not None else 0
        except (TypeError, ValueError):
            max_guests_value = 0
        unit = {
            "name": room.get("name"),
            "max_guests": max_guests,
            "max_children": room.get("max_children"),
            "price": parse_price(room.get("price")),
            "price_text": room.get("price"),
            "currency": room.get("currency"),
            "room_size": room.get("room_size"),
            "bed_configuration": room.get("bed_configuration"),
        }
        if max_guests_value >= args.adults + len(args.child_ages):
            whole_units.append(unit)
        else:
            small_units.append(unit)
    whole_units.sort(key=lambda item: item["price"] or 1e12)
    small_units.sort(key=lambda item: item["max_guests"] or 0, reverse=True)
    return {
        **candidate,
        "property_type": info.get("property_type"),
        "property_name": info.get("name"),
        "city": info.get("city"),
        "whole_units": whole_units[:5],
        "small_units": small_units[:8],
        "best_whole_unit": whole_units[0] if whole_units else None,
    }


def airbnb_detail(
    key: str,
    candidate: dict[str, Any],
    args: argparse.Namespace,
    raw_path: Path,
) -> dict[str, Any]:
    body = call_searchapi(
        key,
        {
            "engine": "airbnb_property",
            "property_id": candidate["raw_property"].get("id"),
            "check_in_date": args.check_in,
            "check_out_date": args.check_out,
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
        "amenities": prop.get("amenities") or [],
    }


def format_price(value: float | None, currency: str = "EUR") -> str:
    if value is None:
        return "—"
    return f"{value:,.0f} {currency}".replace(",", " ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Search ski-resort accommodation via SearchAPI.")
    parser.add_argument("--check-in", default="2027-02-07")
    parser.add_argument("--check-out", default="2027-02-12")
    parser.add_argument("--adults", type=int, default=12)
    parser.add_argument("--child-ages", default="6,9,12")
    parser.add_argument("--currency", default="EUR")
    parser.add_argument("--max-details", type=int, default=2)
    parser.add_argument("--out", default="data/trip_search")
    args = parser.parse_args()
    args.child_ages = [age.strip() for age in args.child_ages.split(",") if age.strip()]
    load_dotenv()
    key = os.environ.get("SEARCHAPI_KEY", "").strip()
    if not key:
        print("Chybí SEARCHAPI_KEY v .env")
        return 2
    run_dir = Path(args.out) / f"{args.check_in}_{args.check_out}"
    run_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for base_key, base in BASES.items():
        print(f"\n### {base['name']}")
        booking_body = call_searchapi(
            key,
            {
                "engine": "booking",
                "q": base["query"],
                "check_in_date": args.check_in,
                "check_out_date": args.check_out,
                "adults": args.adults,
                "children_ages": ",".join(args.child_ages),
                "rooms": 1,
                "currency": args.currency,
                "page": 1,
            },
            run_dir / f"{base_key}_booking_search.json",
        )
        airbnb_body = call_searchapi(
            key,
            {
                "engine": "airbnb",
                "q": base["query"],
                "check_in_date": args.check_in,
                "check_out_date": args.check_out,
                "adults": args.adults,
                "children": len(args.child_ages),
                "currency": args.currency,
            },
            run_dir / f"{base_key}_airbnb_search.json",
        )
        booking_list = booking_candidates(booking_body, base["center"], base["radius_km"])
        airbnb_list = airbnb_candidates(airbnb_body, base["center"], base["radius_km"])
        print(f"Booking: {len(booking_body.get('properties') or [])} vráceno, {len(booking_list)} použitelných v okruhu")
        print(f"Airbnb: {len(airbnb_body.get('properties') or [])} vráceno, {len(airbnb_list)} použitelných v okruhu")

        for index, candidate in enumerate(booking_list[: args.max_details], start=1):
            detail = booking_detail(key, candidate, args, run_dir / f"{base_key}_booking_detail_{index}.json")
            results.append({"base": base["name"], "base_key": base_key, **detail})
        for index, candidate in enumerate(airbnb_list[: args.max_details], start=1):
            detail = airbnb_detail(key, candidate, args, run_dir / f"{base_key}_airbnb_detail_{index}.json")
            results.append({"base": base["name"], "base_key": base_key, **detail})

    (run_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in results:
        print(
            f"{item['base']} | {item['source']} | {item.get('property_name') or item.get('name')} | "
            f"{item['distance_km']} km | {item.get('best_whole_unit') or item.get('guest_capacity')} | "
            f"{format_price(item.get('price'), item.get('currency') or 'EUR')}"
        )
    print(f"\nUloženo: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
