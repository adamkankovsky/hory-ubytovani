#!/usr/bin/env python3
"""Spočítá silniční vzdálenosti jednotek k nejbližším nástupním stanicím lanovek.

Používá veřejný OSRM server (auto). Výsledek se cachuje do
`data/trip_search/road_distances.json`, takže další buildy jsou offline.
Bez sítě (nebo při chybě OSRM) zůstává vzdušná čára z `local_units.py`.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_units import (  # noqa: E402
    LOCAL_AIRBNB,
    RESORTS,
    ROLE_BEDROOMS,
    distance_km,
    nearest_resort,
    parse_local_airbnb_unit,
)

CACHE = ROOT / "data" / "trip_search" / "road_distances.json"
OSRM = "https://router.project-osrm.org/table/v1/driving/"
CANDIDATES = 3
MAX_TABLE = 90


def load_units() -> dict[str, dict]:
    units: dict[str, dict] = {}
    for role in sorted(ROLE_BEDROOMS):
        for path in sorted(LOCAL_AIRBNB.glob(f"*_{role}*.json")):
            for item in json.loads(path.read_text(encoding="utf-8")):
                unit = parse_local_airbnb_unit(item, role)
                if unit is None or unit["id"] in units:
                    continue
                units[unit["id"]] = unit
    return units


def candidates_for(unit: dict) -> list[dict]:
    lifts = RESORTS[unit["resort"]]["points"]
    ranked = sorted(
        lifts,
        key=lambda lift: distance_km(
            (unit["lat"], unit["lng"]), (lift["lat"], lift["lng"])
        ),
    )
    return ranked[:CANDIDATES]


def table(coords: list[tuple[float, float]], sources: list[int], destinations: list[int]) -> list[list]:
    path = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in coords)
    query = urllib.parse.urlencode(
        {
            "sources": ";".join(str(index) for index in sources),
            "destinations": ";".join(str(index) for index in destinations),
            "annotations": "distance",
        }
    )
    url = f"{OSRM}{path}?{query}"
    last_error = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                body = json.load(response)
            if body.get("code") != "Ok":
                raise RuntimeError(body.get("code") or "osrm error")
            return body["distances"]
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"OSRM selhalo: {last_error}")


def main() -> int:
    units = load_units()
    print(f"Jednotek: {len(units)}")
    by_resort: dict[str, list[dict]] = {}
    for unit in units.values():
        by_resort.setdefault(unit["resort"], []).append(unit)

    result: dict[str, dict] = {}
    for resort, resort_units in sorted(by_resort.items()):
        lifts = RESORTS[resort]["points"]
        lift_index = {(lift["lat"], lift["lng"]): index for index, lift in enumerate(lifts)}
        for start in range(0, len(resort_units), MAX_TABLE - len(lifts)):
            batch = resort_units[start:start + MAX_TABLE - len(lifts)]
            coords = [(lift["lat"], lift["lng"]) for lift in lifts] + [
                (unit["lat"], unit["lng"]) for unit in batch
            ]
            unit_offset = len(lifts)
            sources = [unit_offset + index for index in range(len(batch))]
            destinations = list(range(len(lifts)))
            try:
                matrix = table(coords, sources, destinations)
            except Exception as exc:  # noqa: BLE001
                print(f"  {resort}: přeskočeno ({exc})")
                continue
            for row, unit in zip(matrix, batch):
                candidates = candidates_for(unit)
                best = None
                for lift in candidates:
                    index = lift_index[(lift["lat"], lift["lng"])]
                    value = row[index]
                    if value is None:
                        continue
                    if best is None or value < best[0]:
                        best = (value, lift)
                if best is None:
                    continue
                result[unit["id"]] = {
                    "km": round(best[0] / 1000.0, 2),
                    "lift": best[1]["name"],
                }
            print(f"  {resort}: {len(batch)} jednotek hotovo")
            time.sleep(1.1)

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "OSRM /table/v1/driving (auto)",
                "distances": result,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"Uloženo: {CACHE} ({len(result)} jednotek)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
