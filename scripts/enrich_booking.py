#!/usr/bin/env python3
"""Doplní Booking nemovitostem fotku a souřadnice ze stránek výsledků.

Booking vrací v search reportu jen ceny a základní údaje. Stránka výsledků ale
obsahuje embedded JSON se souřadnicemi a fotkami všech zobrazených nemovitostí.
Skript proto načte jen search URL, které obsahují nabídky do cenového stropu
(výchozí 3 500 €), a z každé vytáhne data pro všechny hotely na stránce.

Výsledek se cachuje do `data/trip_search/booking_enrichment.json`.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BOOKING_DIR = ROOT / "data" / "trip_search" / "local_booking"
CACHE = ROOT / "data" / "trip_search" / "booking_enrichment.json"
ROLE_BEDROOMS = {2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 4, 10: 4}

COORDS = re.compile(
    r'"location":\{[^{}]*?"latitude":([\d.]+),"longitude":([\d.]+)[^{}]*?\},"pageName":"([^"]+)"'
)
PHOTO = re.compile(r'"lowResUrl":\{"__typename":"PhotoResource","relativeUrl":"([^"]+)"')


def needed_searches(max_total: float) -> list[str]:
    urls: dict[str, None] = {}
    for path in sorted(BOOKING_DIR.glob("*.json")):
        match = re.match(r".*_(\d+)(_5n)?\.json$", path.name)
        if not match:
            continue
        role = int(match.group(1))
        report = json.loads(path.read_text(encoding="utf-8"))
        query = (report.get("queries") or [{}])[0]
        usable = any(
            offer.get("total_price")
            and offer["total_price"] <= max_total
            and (offer.get("bedrooms") or 0) >= ROLE_BEDROOMS.get(role, 99)
            for offer in query.get("offers") or []
        )
        url = (query.get("applied") or {}).get("url")
        if usable and url:
            urls.setdefault(url, None)
    return list(urls)


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {"hotels": {}, "searches": []}


def save_cache(cache: dict) -> None:
    cache["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cache.setdefault("source", "booking.com search results (embedded JSON + cards)")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def slug_of(url: str) -> str:
    match = re.search(r"/hotel/[a-z]{2}/([^.]+)\.", url)
    return match.group(1) if match else ""


def parse_page(page) -> dict[str, dict]:
    cards = page.evaluate(
        """() => [...document.querySelectorAll('[data-testid="property-card"]')].map(card => ({
            url: card.querySelector('a[href*="/hotel/"]')?.href?.split('?')[0] || null,
            image: card.querySelector('img')?.src || null,
            name: card.querySelector('[data-testid="title"]')?.textContent?.trim() || null
        }))"""
    )
    html = page.content()
    coords = {
        slug: (float(lat), float(lng))
        for lat, lng, slug in COORDS.findall(html)
    }
    photos = {}
    for relative in PHOTO.findall(html):
        photos.setdefault(relative, True)
    result: dict[str, dict] = {}
    for card in cards:
        url = card.get("url")
        if not url:
            continue
        slug = slug_of(url)
        lat, lng = coords.get(slug, (None, None))
        result[url] = {
            "image": card.get("image"),
            "lat": lat,
            "lng": lng,
            "name": card.get("name"),
        }
    # nemovitosti, které jsou v JSON, ale nemají kartu
    for slug, (lat, lng) in coords.items():
        url = f"https://www.booking.com/hotel/at/{slug}.en-gb.html"
        if url in result:
            continue
        result[url] = {"image": None, "lat": lat, "lng": lng, "name": None}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Doplní Booking fotky a souřadnice.")
    parser.add_argument("--max-total", type=float, default=3500)
    args = parser.parse_args()

    searches = needed_searches(args.max_total)
    cache = load_cache()
    done = set(cache.get("searches") or [])
    todo = [url for url in searches if url not in done]
    print(f"search stránek: {len(searches)}, hotovo {len(done & set(searches))}, zbývá {len(todo)}")
    if not todo:
        return 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(locale="en-GB")
        page = context.new_page()
        for index, url in enumerate(todo, start=1):
            try:
                page.goto(url, wait_until="load", timeout=90000)
                page.wait_for_timeout(4000)
                found = parse_page(page)
            except Exception as exc:  # noqa: BLE001
                print(f"  {index}/{len(todo)} chyba: {exc}")
                continue
            cache.setdefault("hotels", {}).update(found)
            cache.setdefault("searches", []).append(url)
            print(f"  {index}/{len(todo)} +{len(found)} nemovitostí (celkem {len(cache['hotels'])})")
            if index % 5 == 0:
                save_cache(cache)
            page.wait_for_timeout(800)
        browser.close()

    save_cache(cache)
    print(f"Uloženo: {CACHE} ({len(cache.get('hotels') or {})} nemovitostí)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
