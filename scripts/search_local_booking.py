#!/usr/bin/env python3
from __future__ import annotations

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
    if not browser_module.playwright_available():
        print("Chybí Playwright. Nainstaluj: pip install 'viajante[browser]' && playwright install chromium")
        return 2
    browser_module.ChromiumSession._start = _start_headful
    OUT.mkdir(parents=True, exist_ok=True)
    for key, (location, lat, lng) in AREAS.items():
        for adults, rooms in ((7, 3), (5, 2)):
            report = viajante.search_hotels(
                [
                    viajante.HotelQuery(
                        location=location,
                        check_in=date(2027, 1, 30),
                        check_out=date(2027, 2, 3),
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
            path = OUT / f"{key}_{adults}.json"
            path.write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"{key} {adults} adults: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
