#!/usr/bin/env python3
"""Předpočítá silniční vzdálenosti mezi jednotlivými ubytováními.

Pro každé středisko spočítá matici vzdáleností (auto) přes OSRM a uloží ji do
`data/trip_search/road_pair_distances.json`. `combine_units.py` ji používá pro
vzdálenost mezi jednotkami ve dvojici; když trasa chybí, spadne na vzdušnou čáru.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from route_distances import load_units, table  # noqa: E402

CACHE = ROOT / "data" / "trip_search" / "road_pair_distances.json"
CHUNK = 50


def main() -> int:
    units = load_units()
    by_resort: dict[str, list[dict]] = {}
    for unit in units.values():
        by_resort.setdefault(unit["resort"], []).append(unit)
    print(f"Jednotek: {len(units)}")

    payload: dict[str, dict] = {}
    for resort, resort_units in sorted(by_resort.items()):
        ids = [unit["id"] for unit in resort_units]
        coords = [(unit["lat"], unit["lng"]) for unit in resort_units]
        count = len(ids)
        km: list[list[float | None]] = [[None] * count for _ in range(count)]
        chunks = [list(range(start, min(start + CHUNK, count))) for start in range(0, count, CHUNK)]
        requests = 0
        for left_index, left in enumerate(chunks):
            for right in chunks[left_index:]:
                block = left + right
                block_coords = [coords[index] for index in block]
                sources = list(range(len(left)))
                destinations = list(range(len(left), len(block)))
                try:
                    matrix = table(block_coords, sources, destinations)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {resort}: blok přeskočen ({exc})")
                    continue
                for row, source in enumerate(left):
                    for column, target in enumerate(right):
                        value = matrix[row][column]
                        if value is None:
                            continue
                        distance = round(value / 1000.0, 2)
                        km[source][target] = distance
                        km[target][source] = distance
                requests += 1
                time.sleep(1.1)
        payload[resort] = {"ids": ids, "km": km}
        print(f"  {resort}: {count} jednotek, {requests} dotazů")

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "OSRM /table/v1/driving (auto)",
                "distances": payload,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Uloženo: {CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
