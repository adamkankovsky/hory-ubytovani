#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import viajante
import viajante.browser as browser_module

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "trip_search" / "local_booking"

AREAS = {
    "katschberg": ("Katschberg, Austria", 47.0605, 13.6185),
    "obertauern": ("Obertauern, Austria", 47.2490, 13.5580),
    "hochkoenig": ("Hochkönig, Austria", 47.3950, 12.9800),
    "nassfeld": ("Nassfeld, Austria", 46.5960, 13.3220),
    "schladming": ("Schladming, Austria", 47.3940, 13.6880),
    "kreischberg": ("Murau, Austria", 47.1110, 14.1690),
    "tauplitz": ("Bad Mitterndorf, Austria", 47.5550, 14.0830),
    "dachstein_west": ("Gosau, Austria", 47.5840, 13.5350),
    "lofer": ("Lofer, Austria", 47.5853, 12.6929),
    "saalbach": ("Saalbach-Hinterglemm, Austria", 47.3910, 12.6350),
    "gastein": ("Bad Hofgastein, Austria", 47.1710, 13.1050),
    "lungau": ("Sankt Michael im Lungau, Austria", 47.0980, 13.6190),
}

# Celý objekt pro 10 osob + menší jednotky pro páry do 10 osob
# (4+6, 5+5, 3+7, 2+8). Kombinace skládá scripts/combine_units.py.
OCCUPANCIES = (
    (10, 4),
    (2, 1),
    (3, 2),
    (4, 2),
    (5, 2),
    (6, 3),
    (7, 3),
    (8, 4),
)

# Primární termín je 4 noci (1. 2. – 5. 2.). Varianta s jedním dnem navíc
# (5 nocí) se hledá taky, protože u některých objektů vyjde celkově levněji.
STAYS = {
    "4n": (date(2027, 2, 1), date(2027, 2, 5)),
    "5n": (date(2027, 2, 1), date(2027, 2, 6)),
}


def _start_headful(self) -> None:
    playwright = browser_module._sync_playwright().start()
    self._pw = playwright
    launch_options: dict[str, object] = {"headless": False}
    if self._config.proxy:
        launch_options["proxy"] = browser_module._playwright_proxy(self._config.proxy)
    browser = playwright.chromium.launch(**launch_options)
    self._browser = browser
    options: dict[str, object] = {
        "locale": self._config.locale,
        "storage_state": str(self._state_path) if self._state_path.exists() else None,
    }
    if self._config.viewport is not None:
        options["viewport"] = dict(self._config.viewport)
    if self._config.user_agent is not None:
        options["user_agent"] = self._config.user_agent
    context = browser.new_context(**options)
    context.route("**/*", self._block_heavy_resources)
    self._context = context


def main() -> int:
    parser = argparse.ArgumentParser(description="Lokální Booking hledání.")
    parser.add_argument("--areas", default="", help="Čárkami oddělený seznam oblastí (výchozí vše).")
    parser.add_argument("--stays", default="", help="Termíny: 4n,5n (výchozí oba).")
    args = parser.parse_args()
    selected = [item.strip() for item in args.areas.split(",") if item.strip()] or list(AREAS)
    stays = [item.strip() for item in args.stays.split(",") if item.strip()] or list(STAYS)
    if not browser_module.playwright_available():
        print("Chybí Playwright. Nainstaluj: pip install 'viajante[browser]' && playwright install chromium")
        return 2
    browser_module.ChromiumSession._start = _start_headful
    OUT.mkdir(parents=True, exist_ok=True)
    for key in selected:
        location, lat, lng = AREAS[key]
        for adults, rooms in OCCUPANCIES:
            for label in stays:
                check_in, check_out = STAYS[label]
                report = viajante.search_hotels(
                    [
                        viajante.HotelQuery(
                            location=location,
                            check_in=check_in,
                            check_out=check_out,
                            adults=adults,
                            rooms=rooms,
                            free_cancellation=False,
                        )
                    ],
                    source="booking",
                    top=20,
                    currency="EUR",
                    near=(lat, lng),
                )
                # 4n varianta zůstává v původním názvu, aby ji vizualizace našla.
                suffix = "" if label == "4n" else f"_{label}"
                path = OUT / f"{key}_{adults}{suffix}.json"
                path.write_text(
                    json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"{key} {adults} adults {check_in}–{check_out}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
