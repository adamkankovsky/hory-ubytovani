#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyairbnb

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "trip_search" / "local_airbnb"

AREAS = {
    "katschberg": [(47.0560, 13.6170), (47.0650, 13.6200)],
    "obertauern": [(47.2490, 13.5580)],
    "hochkoenig": [(47.4060, 12.9030), (47.3830, 12.9990), (47.3830, 13.0500)],
    "nassfeld": [(46.5660, 13.2760), (46.6270, 13.3670)],
    "schladming": [(47.3940, 13.6880), (47.3830, 13.6830), (47.3860, 13.6130), (47.4070, 13.7670), (47.4210, 13.6550)],
    "tauplitz": [(47.5580, 14.0480)],
    "kreischberg": [(47.1170, 14.1830), (47.2500, 14.2830)],
    "dachstein_west": [(47.5840, 13.5350), (47.5140, 13.4330), (47.5910, 13.4660)],
    "lofer": [(47.5853, 12.6929), (47.5642, 12.7058)],
    "saalbach": [(47.3910, 12.6350), (47.3770, 12.5950), (47.4390, 12.7490), (47.4270, 12.8480)],
    "gastein": [(47.1710, 13.1050), (47.1160, 13.1350), (47.0470, 13.0170)],
    "lungau": [(47.0980, 13.6190), (47.1330, 13.6780)],
}

ROLES = {
    # 10 osob = celý objekt pro celou skupinu.
    10: 4,
    # Menší jednotky pro páry do 10 osob (4+6, 5+5, 3+7, 2+8).
    # Kombinace skládá scripts/combine_units.py.
    2: 1,
    3: 2,
    4: 2,
    5: 2,
    6: 3,
    7: 3,
    8: 4,
}

# Primární termín je 4 noci (1. 2. – 5. 2.). Varianta s jedním dnem navíc
# (5 nocí) se hledá taky, protože u některých objektů vyjde celkově levněji.
STAYS = {
    "4n": ("2027-02-01", "2027-02-05"),
    "5n": ("2027-02-01", "2027-02-06"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Lokální Airbnb hledání.")
    parser.add_argument("--areas", default="", help="Čárkami oddělený seznam oblastí (výchozí vše).")
    parser.add_argument("--stays", default="", help="Termíny: 4n,5n (výchozí oba).")
    args = parser.parse_args()
    selected = [item.strip() for item in args.areas.split(",") if item.strip()] or list(AREAS)
    stays = [item.strip() for item in args.stays.split(",") if item.strip()] or list(STAYS)
    OUT.mkdir(parents=True, exist_ok=True)
    padding = 0.25
    for area in selected:
        points = AREAS[area]
        lats = [point[0] for point in points]
        lngs = [point[1] for point in points]
        bounds = {
            "ne_lat": max(lats) + padding,
            "ne_long": max(lngs) + padding,
            "sw_lat": min(lats) - padding,
            "sw_long": min(lngs) - padding,
        }
        for adults, min_bedrooms in ROLES.items():
            for label in stays:
                check_in, check_out = STAYS[label]
                rooms = pyairbnb.search_first_page(
                    check_in=check_in,
                    check_out=check_out,
                    zoom_value=11,
                    price_min=0,
                    price_max=10000,
                    adults=adults,
                    children=0,
                    infants=0,
                    min_bedrooms=min_bedrooms,
                    currency="EUR",
                    language="en",
                    timeout=90,
                    **bounds,
                )
                # 4n varianta zůstává v původním názvu, aby ji vizualizace našla.
                suffix = "" if label == "4n" else f"_{label}"
                path = OUT / f"{area}_{adults}{suffix}.json"
                path.write_text(json.dumps(rooms, ensure_ascii=False, indent=2), encoding="utf-8")
                print(
                    f"{area} {adults} adults {check_in}–{check_out}: "
                    f"{len(rooms)} results -> {path}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
