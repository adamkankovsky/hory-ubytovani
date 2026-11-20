"""Společné helpery pro lokální hledače a skládání kombinací."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOCAL_AIRBNB = ROOT / "data" / "trip_search" / "local_airbnb"
LOCAL_BOOKING = ROOT / "data" / "trip_search" / "local_booking"

# Minimální počet ložnic pro jednotku dané velikosti (počet osob).
ROLE_BEDROOMS = {2: 1, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 4, 10: 4}

# Nástupní (dolní) stanice lanovek podle OpenStreetMap (Overpass, 20. 11. 2026).
# Vzdálenost jednotky se počítá k nejbližší z nich, ne k vrcholovým stanicím.
# Nástupní (dolní) stanice lanovek podle OpenStreetMap (Overpass, 20. 11. 2026).
# Dolní konec je určený podle nadmořské výšky (EU-DEM), ne podle blízkosti města.
# Vzdálenost jednotky se počítá k nejbližší z nich, ne k vrcholovým stanicím.
# Nástupní (dolní) stanice lanovek podle OpenStreetMap (Overpass, 20. 11. 2026).
# Dolní konec je určený podle nadmořské výšky (EU-DEM), ne podle blízkosti města.
# Berou se jen lanovky, jejichž dolní stanice je do 6,5 km od vstupního bodu areálu.
# Vzdálenost jednotky se počítá k nejbližší z nich, ne k vrcholovým stanicím.
RESORTS = {
    "Tauplitz / Schneebären": {
        "color": "#2563eb",
        "center": {"name": "Bergbahn Tauplitz I", "lat": 47.56254, "lng": 14.01242},
        "points": [
            {"name": "Kulmlift", "lat": 47.54808, "lng": 13.99421},
            {"name": "Bergbahn Tauplitz I", "lat": 47.56254, "lng": 14.01242},
            {"name": "Grafenwiesenlift", "lat": 47.56538, "lng": 14.01023},
            {"name": "Spechtenseelift", "lat": 47.56145, "lng": 14.08324},
            {"name": "Bergbahn Tauplitz II", "lat": 47.57907, "lng": 14.00538},
            {"name": "Mitterstein", "lat": 47.58017, "lng": 13.97605},
            {"name": "Großseelift I", "lat": 47.59872, "lng": 13.99544},
            {"name": "Lawinenstein", "lat": 47.59498, "lng": 13.98523},
            {"name": "Lärchkogellift", "lat": 47.59665, "lng": 13.98895},
        ],
    },
    "Kreischberg + Lachtal": {
        "color": "#16a34a",
        "center": {"name": "Kreischberg 10er I", "lat": 47.09898, "lng": 14.08538},
        "points": [
            {"name": "Kreischberg 10er I", "lat": 47.09898, "lng": 14.08538},
            {"name": "Lachtal", "lat": 47.25171, "lng": 14.36562},
            {"name": "Schönberg Schaukel", "lat": 47.25899, "lng": 14.36663},
            {"name": "Zinkenlift", "lat": 47.26287, "lng": 14.34760},
        ],
    },
    "Dachstein West": {
        "color": "#d97706",
        "center": {"name": "Hornspitz Express I", "lat": 47.56687, "lng": 13.51846},
        "points": [
            {"name": "Hornspitz Express I", "lat": 47.56687, "lng": 13.51846},
            {"name": "Kopfbergbahn", "lat": 47.51181, "lng": 13.43139},
            {"name": "Hornbahn", "lat": 47.58870, "lng": 13.46248},
            {"name": "Panorama Jet Zwieselalm", "lat": 47.54509, "lng": 13.50358},
            {"name": "Astauwinkel", "lat": 47.51993, "lng": 13.44865},
            {"name": "Donnerkogelbahn", "lat": 47.51844, "lng": 13.45088},
            {"name": "Lammertallift", "lat": 47.49960, "lng": 13.37589},
            {"name": "Gosaukammbahn", "lat": 47.53311, "lng": 13.49645},
            {"name": "Hornspitz Express II", "lat": 47.56658, "lng": 13.49733},
            {"name": "Hochkögllift", "lat": 47.54366, "lng": 13.48579},
            {"name": "Edtalmbahn", "lat": 47.55570, "lng": 13.47376},
            {"name": "Höhbühelbahn", "lat": 47.55429, "lng": 13.47770},
            {"name": "Angeralmbahn", "lat": 47.53874, "lng": 13.46424},
            {"name": "Ochsenkoplift", "lat": 47.56538, "lng": 13.47951},
            {"name": "Törleckbahn", "lat": 47.53412, "lng": 13.48094},
        ],
    },
    "Schladming 4 Berge": {
        "color": "#dc2626",
        "center": {"name": "Planaibahn I", "lat": 47.39289, "lng": 13.69322},
        "points": [
            {"name": "Hauser Kaiblingbahn", "lat": 47.41152, "lng": 13.77956},
            {"name": "Planai West I", "lat": 47.39038, "lng": 13.67752},
            {"name": "Planaibahn I", "lat": 47.39289, "lng": 13.69322},
            {"name": "Hochwurzen 1", "lat": 47.38585, "lng": 13.61289},
            {"name": "Silver Jet", "lat": 47.38847, "lng": 13.59766},
            {"name": "Schladminger Tauern Seilbahn", "lat": 47.40622, "lng": 13.76664},
            {"name": "Planai West II", "lat": 47.38336, "lng": 13.68615},
            {"name": "Fageralmbahn", "lat": 47.37765, "lng": 13.54627},
            {"name": "Rohrmoos II", "lat": 47.38542, "lng": 13.66514},
            {"name": "Obertalbahn", "lat": 47.37544, "lng": 13.66249},
            {"name": "Preunegg Jet", "lat": 47.37468, "lng": 13.61355},
            {"name": "Fastenberg 6er", "lat": 47.39017, "lng": 13.70859},
            {"name": "chair_lift", "lat": 47.41755, "lng": 13.65512},
            {"name": "Gipfelbahn Hochwurzen", "lat": 47.37611, "lng": 13.65400},
            {"name": "Höfi-Express I", "lat": 47.39868, "lng": 13.78951},
            {"name": "Drachenlift II", "lat": 47.40846, "lng": 13.63656},
            {"name": "Drachenlift I", "lat": 47.41062, "lng": 13.63686},
            {"name": "Rittislift", "lat": 47.41514, "lng": 13.62785},
            {"name": "Schneemandl Lift", "lat": 47.42695, "lng": 13.67691},
            {"name": "Bergkristalllift", "lat": 47.42571, "lng": 13.65050},
            {"name": "drag_lift", "lat": 47.42490, "lng": 13.62369},
            {"name": "Rittisbergbahn", "lat": 47.42240, "lng": 13.62367},
            {"name": "Zauberlift", "lat": 47.42683, "lng": 13.62163},
            {"name": "Kaibling 6er", "lat": 47.39597, "lng": 13.77489},
            {"name": "Hochwurzen 2", "lat": 47.37547, "lng": 13.63205},
            {"name": "Planaibahn II", "lat": 47.38214, "lng": 13.70774},
            {"name": "Senderbahn", "lat": 47.36775, "lng": 13.75631},
            {"name": "Gasselhöhe II", "lat": 47.37192, "lng": 13.59151},
            {"name": "Sepp'n Jet Reiteralm II", "lat": 47.37321, "lng": 13.60170},
            {"name": "Kaiblinggrat", "lat": 47.38963, "lng": 13.77613},
            {"name": "Höfi-Express II", "lat": 47.38899, "lng": 13.78698},
            {"name": "Mitterhausbahn", "lat": 47.36933, "lng": 13.74179},
            {"name": "Burgstallalmbahn", "lat": 47.37788, "lng": 13.73045},
            {"name": "Schoberbahn", "lat": 47.36108, "lng": 13.60373},
            {"name": "Alm 6er", "lat": 47.36764, "lng": 13.76556},
            {"name": "Weitmooslift", "lat": 47.36745, "lng": 13.71407},
            {"name": "Märchenwiesebahn", "lat": 47.36989, "lng": 13.71675},
            {"name": "Gipfelbahn", "lat": 47.37558, "lng": 13.77225},
        ],
    },
    "Katschberg – Aineck": {
        "color": "#7c3aed",
        "center": {"name": "Almbahn", "lat": 47.05820, "lng": 13.61730},
        "points": [
            {"name": "Petersbründllift", "lat": 47.09011, "lng": 13.62729},
            {"name": "Silverjet I", "lat": 47.08028, "lng": 13.68905},
            {"name": "Sonnenbahn", "lat": 47.10095, "lng": 13.64792},
            {"name": "Silverjet II", "lat": 47.07011, "lng": 13.67291},
            {"name": "Königswiesenbahn", "lat": 47.06385, "lng": 13.61251},
            {"name": "Tschaneckbahn", "lat": 47.06017, "lng": 13.61097},
            {"name": "Tellerlift", "lat": 47.05367, "lng": 13.61246},
            {"name": "Almbahn", "lat": 47.05820, "lng": 13.61730},
            {"name": "Sonnleitenlift", "lat": 47.04660, "lng": 13.60616},
            {"name": "Gamskogelexpress", "lat": 47.05572, "lng": 13.61122},
            {"name": "Freiberglift", "lat": 47.05044, "lng": 13.60737},
            {"name": "Sonnalmbahn", "lat": 47.05830, "lng": 13.60599},
            {"name": "Gipfelbahn", "lat": 47.06096, "lng": 13.66062},
            {"name": "Ainecklift", "lat": 47.06082, "lng": 13.65795},
        ],
    },
    "Obertauern": {
        "color": "#0891b2",
        "data_note": "Většina nabídek je jen na Bookingu; Booking neuvádí souřadnice, takže vzdálenost k lanovce nelze ověřit.",
        "center": {"name": "Zentralbahn", "lat": 47.25189, "lng": 13.55746},
        "points": [
            {"name": "Achenrainbahn", "lat": 47.24167, "lng": 13.57085},
            {"name": "Kehrkopfbahn", "lat": 47.25391, "lng": 13.52737},
            {"name": "Zehnerkarbahn", "lat": 47.25088, "lng": 13.54551},
            {"name": "Kirchbühellift", "lat": 47.25025, "lng": 13.54828},
            {"name": "Edelweissbahn", "lat": 47.24596, "lng": 13.56714},
            {"name": "Zentralbahn", "lat": 47.25189, "lng": 13.55746},
            {"name": "Monte Flu-Bahn", "lat": 47.25263, "lng": 13.54026},
            {"name": "Gamsleitenbahn I", "lat": 47.24660, "lng": 13.56072},
            {"name": "Pernerlift", "lat": 47.24886, "lng": 13.55848},
            {"name": "Angerbahn", "lat": 47.25852, "lng": 13.56497},
            {"name": "Schönalmbahn", "lat": 47.26264, "lng": 13.56548},
            {"name": "Kringsalmbahn", "lat": 47.26423, "lng": 13.56354},
            {"name": "Gamsleitenbahn 2", "lat": 47.24088, "lng": 13.55911},
            {"name": "Hochalmbahn", "lat": 47.26162, "lng": 13.54530},
            {"name": "Zehnerkarbahn", "lat": 47.24217, "lng": 13.54135},
        ],
    },
    "Hochkönig": {
        "color": "#be123c",
        "center": {"name": "Natrunbahn", "lat": 47.40633, "lng": 12.90625},
        "points": [
            {"name": "Hinterreitlift I", "lat": 47.40821, "lng": 12.88767},
            {"name": "Natrunlift", "lat": 47.40399, "lng": 12.90426},
            {"name": "Natrunbahn", "lat": 47.40633, "lng": 12.90625},
            {"name": "Abergbahn", "lat": 47.38974, "lng": 12.90895},
            {"name": "Hinterreitlift II", "lat": 47.40351, "lng": 12.88667},
            {"name": "SINALCObahn", "lat": 47.38710, "lng": 12.93882},
            {"name": "Karbachalm", "lat": 47.37966, "lng": 13.10918},
            {"name": "Hochmais", "lat": 47.40544, "lng": 12.97136},
            {"name": "Faschinglift 1", "lat": 47.40844, "lng": 12.97856},
            {"name": "Sonnleitenlift", "lat": 47.41121, "lng": 12.97766},
            {"name": "Schönanger", "lat": 47.38264, "lng": 12.91119},
            {"name": "Gabühelbahn", "lat": 47.38459, "lng": 13.00476},
            {"name": "Liebenaulift", "lat": 47.38854, "lng": 13.02831},
            {"name": "Abergalm", "lat": 47.37162, "lng": 12.91697},
            {"name": "Karlift", "lat": 47.37396, "lng": 12.91098},
            {"name": "Dachegg", "lat": 47.38894, "lng": 13.03390},
            {"name": "Kings Cab", "lat": 47.38544, "lng": 13.07322},
            {"name": "Saukarlift", "lat": 47.40007, "lng": 13.11677},
            {"name": "Griesfeldlift", "lat": 47.40408, "lng": 13.12025},
            {"name": "Roßwieslift", "lat": 47.40758, "lng": 13.12729},
            {"name": "Wastlhöhelift", "lat": 47.37226, "lng": 13.01715},
        ],
    },
    "Nassfeld": {
        "color": "#65a30d",
        "center": {"name": "Millennium-Express Sektion I", "lat": 46.61147, "lng": 13.27936},
        "points": [
            {"name": "Millennium-Express Sektion I", "lat": 46.61147, "lng": 13.27936},
            {"name": "Millennium-Express Sektion II", "lat": 46.59752, "lng": 13.27331},
            {"name": "Trogkofelbahn", "lat": 46.57773, "lng": 13.24263},
            {"name": "Sonnleitn-4er-Sesselbahn", "lat": 46.58445, "lng": 13.25876},
            {"name": "Gartnerkofelbahn", "lat": 46.56670, "lng": 13.27760},
            {"name": "Madritschen", "lat": 46.56276, "lng": 13.27446},
            {"name": "6er-SB Garnitzen I \"La Prima\"", "lat": 46.56037, "lng": 13.31598},
            {"name": "Watschiger-Alm-Lift", "lat": 46.56815, "lng": 13.28692},
            {"name": "Millennium-Express Sektion III", "lat": 46.57426, "lng": 13.26139},
            {"name": "6er Mössernbahn", "lat": 46.56745, "lng": 13.24409},
            {"name": "Kanonenrohrlift", "lat": 46.56086, "lng": 13.26404},
            {"name": "4er-SB FIS", "lat": 46.56573, "lng": 13.30042},
        ],
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


def nearest_resort(lat: float, lng: float) -> tuple[str, dict[str, Any], float]:
    best: tuple[str, dict[str, Any], float] | None = None
    for name, resort in RESORTS.items():
        for point in resort["points"]:
            dist = distance_km((lat, lng), (point["lat"], point["lng"]))
            if best is None or dist < best[2]:
                best = (name, point, dist)
    assert best is not None
    return best


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
    if bedrooms is None or bedrooms < ROLE_BEDROOMS[role]:
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
