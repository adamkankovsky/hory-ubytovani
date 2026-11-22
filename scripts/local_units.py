"""Společné helpery pro lokální hledače a skládání kombinací."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOCAL_AIRBNB = ROOT / "data" / "trip_search" / "local_airbnb"
LOCAL_BOOKING = ROOT / "data" / "trip_search" / "local_booking"
BOOKING_ENRICHMENT = ROOT / "data" / "trip_search" / "booking_enrichment.json"
PRICE_CAP = 3500.0

BOOKING_AREAS = {
    "katschberg": "Katschberg – Aineck",
    "obertauern": "Obertauern",
    "hochkoenig": "Hochkönig",
    "nassfeld": "Nassfeld",
    "schladming": "Schladming 4 Berge",
    "kreischberg": "Kreischberg + Lachtal",
    "tauplitz": "Tauplitz / Schneebären",
    "dachstein_west": "Dachstein West",
    "lofer": "Almenwelt Lofer",
    "saalbach": "Skicircus Saalbach",
    "gastein": "Gastein",
    "lungau": "Lungau",
}

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
            {"name": "Dachstein Südwandbahn", "lat": 47.45099, "lng": 13.61804},
            {"name": "Märchenwiesebahn", "lat": 47.36989, "lng": 13.71675},
            {"name": "Gipfelbahn", "lat": 47.37558, "lng": 13.77225},
            {"name": "Bundesheer-Seilbahn", "lat": 47.46805, "lng": 13.62639},
        ],
    },
    "Katschberg – Aineck": {
        "color": "#7c3aed",
        "center": {"name": "Almbahn", "lat": 47.05820, "lng": 13.61730},
        "points": [
            {"name": "Silverjet I", "lat": 47.08028, "lng": 13.68905},
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
    "Almenwelt Lofer": {
        "color": "#475569",
        "center": {"name": "Almbahn I", "lat": 47.58775, "lng": 12.69139},
        "points": [
            {"name": "Almbahn I", "lat": 47.58775, "lng": 12.69139},
            {"name": "Postalmlift", "lat": 47.60177, "lng": 12.68405},
            {"name": "Almbahn II", "lat": 47.60444, "lng": 12.68250},
            {"name": "Senderexpress", "lat": 47.60691, "lng": 12.63791},
            {"name": "Almen 8er Schwarzeck", "lat": 47.60811, "lng": 12.65656},
        ],
    },
    "Skicircus Saalbach": {
        "color": "#a16207",
        "center": {"name": "Schattberg X-Press I", "lat": 47.39030, "lng": 12.63528},
        "points": [
            {"name": "Biberg Bahn", "lat": 47.42261, "lng": 12.81336},
            {"name": "Steinbergbahn I", "lat": 47.43955, "lng": 12.73310},
            {"name": "Asitzbahn I", "lat": 47.43925, "lng": 12.71883},
            {"name": "Schönleitenbahn I", "lat": 47.37883, "lng": 12.67601},
            {"name": "Schattberg X-Press I", "lat": 47.39030, "lng": 12.63528},
            {"name": "Bernkogelbahn", "lat": 47.39305, "lng": 12.63596},
            {"name": "Kohlmaisbahn I", "lat": 47.39208, "lng": 12.64018},
            {"name": "Mitteregglift", "lat": 47.38208, "lng": 12.60695},
            {"name": "Bergfriedlift", "lat": 47.37913, "lng": 12.60025},
            {"name": "Almbahn", "lat": 47.43556, "lng": 12.70821},
            {"name": "Reiterkogelbahn I", "lat": 47.37952, "lng": 12.59678},
            {"name": "Unterschwarzachbahn", "lat": 47.37689, "lng": 12.59443},
            {"name": "12er KOGELbahn 1", "lat": 47.37544, "lng": 12.58926},
            {"name": "12er Express", "lat": 47.37491, "lng": 12.59339},
            {"name": "TirolS I", "lat": 47.41760, "lng": 12.57822},
            {"name": "Westgipfelbahn I", "lat": 47.37286, "lng": 12.59326},
            {"name": "12er NORD", "lat": 47.37595, "lng": 12.56295},
            {"name": "Reckmoos Süd", "lat": 47.41755, "lng": 12.56827},
            {"name": "Asitzbahn II", "lat": 47.42748, "lng": 12.71393},
            {"name": "Sunliner 4er", "lat": 47.39052, "lng": 12.60072},
            {"name": "Hochalm 6er", "lat": 47.38274, "lng": 12.55588},
            {"name": "Panorama 6er", "lat": 47.39858, "lng": 12.64902},
            {"name": "Magic 6er (Bergeralm)", "lat": 47.39901, "lng": 12.65949},
            {"name": "Kohlmaisbahn II", "lat": 47.40089, "lng": 12.64633},
            {"name": "Steinbergbahn II", "lat": 47.42047, "lng": 12.73084},
            {"name": "Schattberg X-Press II", "lat": 47.38040, "lng": 12.63292},
            {"name": "Reiterkogelbahn II", "lat": 47.38863, "lng": 12.58910},
            {"name": "Westgipfelbahn II", "lat": 47.36562, "lng": 12.60504},
            {"name": "Schönleitenbahn II", "lat": 47.39167, "lng": 12.68304},
            {"name": "Zehner 6er", "lat": 47.34927, "lng": 12.57851},
            {"name": "Rosswaldbahn", "lat": 47.38839, "lng": 12.57091},
            {"name": "12er KOGELbahn 2", "lat": 47.36311, "lng": 12.58131},
            {"name": "Bernkogel 6er", "lat": 47.40280, "lng": 12.61688},
            {"name": "Limberg 8er", "lat": 47.36106, "lng": 12.65248},
            {"name": "Reiter-Ost 6er", "lat": 47.40902, "lng": 12.59584},
            {"name": "Asitzgipfelbahn 8er", "lat": 47.41170, "lng": 12.71862},
            {"name": "Polten 8er", "lat": 47.39733, "lng": 12.69361},
            {"name": "Asitzkogelbahn", "lat": 47.40295, "lng": 12.71311},
            {"name": "drag_lift", "lat": 47.35677, "lng": 12.57613},
            {"name": "Hochhörndl 4er", "lat": 47.42479, "lng": 12.55854},
            {"name": "Seekarlift", "lat": 47.34831, "lng": 12.56442},
            {"name": "Schattberg Sprinter", "lat": 47.36754, "lng": 12.63032},
        ],
    },
    "Gastein": {
        "color": "#0f766e",
        "center": {"name": "Schlossalmbahn I", "lat": 47.16777, "lng": 13.09824},
        "points": [
            {"name": "Schlossalmbahn I", "lat": 47.16777, "lng": 13.09824},
            {"name": "Graukogel I", "lat": 47.11608, "lng": 13.13980},
            {"name": "Stubnerkogelbahn I", "lat": 47.11051, "lng": 13.13150},
            {"name": "ESL Bellevuealm", "lat": 47.11641, "lng": 13.13190},
            {"name": "Kaserebenbahn", "lat": 47.13172, "lng": 13.08144},
            {"name": "Schlossalmbahn II", "lat": 47.16511, "lng": 13.08250},
            {"name": "Senderbahn II", "lat": 47.12509, "lng": 13.08185},
            {"name": "Graukogel II", "lat": 47.11139, "lng": 13.15055},
            {"name": "Sendleitenbahn", "lat": 47.15405, "lng": 13.07827},
            {"name": "Goldbergbahn I", "lat": 47.06215, "lng": 13.05873},
            {"name": "Jungeralmbahn", "lat": 47.11767, "lng": 13.08329},
            {"name": "Reichebenlift", "lat": 47.11308, "lng": 13.16297},
            {"name": "Burgstalllift", "lat": 47.12415, "lng": 13.10214},
            {"name": "Stubnerkogelbahn II", "lat": 47.11140, "lng": 13.11214},
            {"name": "Weitmoser", "lat": 47.14718, "lng": 13.06499},
            {"name": "Schlosshochalmlift", "lat": 47.14623, "lng": 13.06252},
            {"name": "Goldbergbahn II", "lat": 47.05982, "lng": 13.06815},
            {"name": "Hohe Scharte", "lat": 47.14924, "lng": 13.05321},
            {"name": "Schwarzkopfbahn", "lat": 47.01232, "lng": 13.02500},
            {"name": "Kreuzkogellift", "lat": 47.05982, "lng": 13.07587},
            {"name": "Eisseebahn", "lat": 47.01638, "lng": 13.01590},
            {"name": "Alteck", "lat": 47.03254, "lng": 12.99565},
            {"name": "Panoramabahn Klühspies", "lat": 47.03380, "lng": 12.99820},
            {"name": "Gletscher Jet", "lat": 47.03427, "lng": 13.00933},
        ],
    },
    "Lungau": {
        "color": "#1e40af",
        "center": {"name": "Großeckbahn", "lat": 47.14183, "lng": 13.66306},
        "points": [
            {"name": "Petersbründllift", "lat": 47.09011, "lng": 13.62729},
            {"name": "Sonnenbahn", "lat": 47.10095, "lng": 13.64792},
            {"name": "Großeckbahn", "lat": 47.14183, "lng": 13.66306},
            {"name": "Samson-Sesselbahn", "lat": 47.16929, "lng": 13.69345},
            {"name": "Moserkopflift", "lat": 47.14989, "lng": 13.67642},
            {"name": "Zirbenjet", "lat": 47.17581, "lng": 13.67343},
            {"name": "Sonnenalm", "lat": 47.12458, "lng": 13.65230},
            {"name": "Stockerboden", "lat": 47.12186, "lng": 13.65952},
            {"name": "Großeckbahn II", "lat": 47.12916, "lng": 13.65580},
            {"name": "Speiereck-Gipfelbahn", "lat": 47.12385, "lng": 13.64860},
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
    if not price or float(price) > PRICE_CAP:
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


def load_booking_enrichment() -> dict[str, dict[str, Any]]:
    if not BOOKING_ENRICHMENT.exists():
        return {}
    try:
        data = json.loads(BOOKING_ENRICHMENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data.get("hotels") or {}


BOOKING_ENRICHMENT_DATA = load_booking_enrichment()


def parse_booking_offer(
    offer: dict[str, Any], role: int, area_key: str
) -> dict[str, Any] | None:
    price = offer.get("total_price")
    bedrooms = offer.get("bedrooms") or 0
    url = offer.get("link")
    if not price or not url:
        return None
    # Booking u celých domů často uvádí jen část ložnic (prodává kombinaci
    # pokojů), takže u entire_home věříme obsazenosti z vyhledávání.
    lodging_kind = offer.get("lodging_kind")
    minimum_bedrooms = 1 if lodging_kind == "entire_home" else ROLE_BEDROOMS[role]
    if bedrooms < minimum_bedrooms:
        return None
    if float(price) > PRICE_CAP:
        return None
    title = offer.get("title") or "Booking"
    enrichment = BOOKING_ENRICHMENT_DATA.get(url) or {}
    lat = offer.get("latitude")
    lng = offer.get("longitude")
    if lat is None or lng is None:
        lat, lng = enrichment.get("lat"), enrichment.get("lng")
    resort_km = None
    resort_point = None
    if lat is not None and lng is not None:
        resort_name, resort_point, resort_km = nearest_resort(float(lat), float(lng))
        if resort_km > 25:
            return None
    else:
        resort_name = BOOKING_AREAS[area_key]
        match = re.search(r"([\d.]+)\s*km from", str(offer.get("details") or ""))
        if match:
            resort_km = float(match.group(1))
    details = str(offer.get("details") or "")
    multi_unit = len(re.findall(r"\d+×", details)) > 1
    return {
        "provider": "Booking",
        "multi_unit": multi_unit,
        "role": str(role),
        "id": f"booking:{url}:{title}:{role}",
        "title": title,
        "url": url,
        "price": float(price),
        "capacity": role,
        "bedrooms": bedrooms,
        "lat": None if lat is None else float(lat),
        "lng": None if lng is None else float(lng),
        "resort": resort_name,
        "resort_point": resort_point,
        "resort_km": None if resort_km is None else round(resort_km, 2),
        "image": enrichment.get("image"),
        "rating": offer.get("rating_score"),
        "reviews": offer.get("review_count"),
        "location": offer.get("address"),
        "address": offer.get("address"),
        "lodging_kind": offer.get("lodging_kind"),
        "type": "Booking local",
    }


def load_booking_role(role: int, suffix: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for key in BOOKING_AREAS:
        path = LOCAL_BOOKING / f"{key}_{role}{suffix}.json"
        if not path.exists():
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        for offer in (report.get("queries") or [{}])[0].get("offers") or []:
            unit = parse_booking_offer(offer, role, key)
            if unit is None:
                continue
            grouped.setdefault(unit["resort"], []).append(unit)
    return grouped
