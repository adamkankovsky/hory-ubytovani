# Hory — ověření StayingAPI

Malý nástroj pro bod 1 návrhu: ověří, co StayingAPI skutečně vrací pro jednu
rakouskou lokalitu, jeden termín a skupinu 12 dospělých + 3 děti.

Nástroj:

- hledá celou skupinu i několik menších obsazení;
- stahuje detaily a konkrétní ceny vybraných nabídek;
- ukládá všechny raw odpovědi, manifest volání a přehled kandidátů;
- odpovídá na pět ověřovacích otázek ze zadání;
- měří skutečnou spotřebu kreditů a počítá worst-case pro další běhy.

Není to ještě aplikace ani MCP. Je to jednorázový probe, ze kterého vzejde
rozhodnutí, zda StayingAPI stačí pro kombinování více jednotek ve stejném domě.

## Bezpečnost klíče

Klíč patří pouze do `.env` nebo do proměnné prostředí. Nikdy ho necommituj a
nevkládej do reportu. Nástroj ho nikam nezapisuje; manifest obsahuje jen
parametry dotazů, ne hlavičku `Authorization`.

## Instalace

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Do `.env` vlož svůj klíč:

```dotenv
STAYINGAPI_KEY=stay_live_...
```

Live klíč (`stay_live_`) je potřeba pro skutečné ověření. Sandbox
(`stay_test_`) vrací deterministické fixtures, takže neodpovídá na otázky o
reálné nabídce; nástroj ho pustí jen s `--allow-sandbox`.

## Nejdřív dry-run

Dry-run nic nevolá, nic nezapisuje a nepotřebuje klíč. Ukáže plán dotazů a
worst-case spotřebu:

```bash
python probe_stayingapi.py --dry-run
```

Výchozí plán:

- lokalita `Schladming, Austria`, okruh 20 km;
- termín `2027-07-03` → `2027-07-07` (4 noci);
- 12 dospělých + děti ve věku 6, 9 a 12 let;
- platformy `airbnb,booking`, limit 10 výsledků na platformu a dotaz, `rooms=1`;
- celá skupina + 5 menších obsazení (8A+2C, 6A+1C, 4A+2C, 4A, 2A);
- 6 kandidátů na detail, 2 kandidáti na cenový test menšího obsazení;
- rozpočet 250 kreditů.

## Reálné ověření

```bash
python probe_stayingapi.py
```

Živé hledání může běžet minuty: API vrací `202` s `jobId` a nástroj průběžně
polluje `/v1/jobs/{jobId}`. Polling je zdarma, práce se účtuje až po dokončení.

Užitečné volby:

```bash
# jiný termín a skupina
python probe_stayingapi.py \
  --check-in 2027-02-06 --nights 4 \
  --adults 12 --children 6,9,12

# více platforem, ale dražší
python probe_stayingapi.py --platforms airbnb,booking,vrbo

# Booking.com: zkusit search pro více pokojů
python probe_stayingapi.py --rooms 3

# širší vzorek (pozor na kredity)
python probe_stayingapi.py --limit 20 --detail-candidates 10

# vlastní menší obsazení
python probe_stayingapi.py --sub-occupancies "8A+2C,4A+2C,4A,2A"

# levnější běh
python probe_stayingapi.py --max-credits 120 --detail-candidates 4 --split-probes 1

# po výpadku upstreamu pokračovat i dalšími obsazeními (jinak se běh zastaví)
python probe_stayingapi.py --continue-on-upstream-error

# pouze znovu analyzovat uložená raw data, bez volání API
python probe_stayingapi.py --reanalyze data/runs/20261118-120000-schladming-austria
```

## Výstup

Každý běh vytvoří `data/runs/<čas>-<lokalita>/`:

| Soubor | Obsah |
|---|---|
| `report.md` | Český report s odpověďmi, tabulkami, limity a doporučením |
| `summary.json` | Strukturovaný výsledek pro další vývoj |
| `candidates.csv` | Tabulka unikátních nabídek |
| `analysis_inputs.json` | Konfigurace a odkazy na raw soubory pro `--reanalyze` |
| `manifest.jsonl` | Každé volání: parametry, HTTP status, kredity, requestId, raw soubor |
| `raw/` | Kompletní JSON odpovědi |

Report odpovídá na:

1. zda je nabídka konkrétní apartmán, nebo celý dům;
2. zda API vrací kapacitu, polohu a použitelné identifikátory;
3. zda lze cenu ověřit pro konkrétní rozdělení dospělých a dětí;
4. zda lze rozlišit jednotky ve stejném domě;
5. kolik stojí jedno kompletní hledání v kreditech.

## Když search selže

Když API vrátí `upstream_unavailable` / `all_actors_failed`, nejde o nulovou
nabídku. Znamená to, že se nepodařilo získat data z upstreamu (Airbnb,
Booking.com, Vrbo nebo Google). Taková volání jsou zdarma, ale běh nemá smysl
donekonečna opakovat:

- nástroj se po prvním takovém selhání zastaví, aby nečekal na circuit breaker;
- report výslovně napíše, že hledání selhalo, a vypíše requestId;
- `--continue-on-upstream-error` vynutí pokusy i o další obsazení;
- malý diagnostický dotaz:

```bash
python probe_stayingapi.py \
  --platforms booking --limit 5 --max-sub-searches 0 \
  --detail-candidates 0 --split-probes 0 --max-credits 10
```

Pokud se `all_actors_failed` opakuje i pro jinou lokalitu a malou skupinu,
zkontrolujte `status.stayingapi.com` a kontaktujte podporu StayingAPI s
requestId z reportu. Teprve úspěšný live běh může rozhodnout bod 1.

## Jak číst výsledek

- `ANO` znamená, že to vzorek podporuje.
- `ČÁSTEČNĚ` znamená, že API něco vrací, ale je potřeba další ověření.
- `NELZE URČIT` znamená, že z daných dat nelze udělat závěr.
- `NE` znamená, že to API na vzorku neumožnilo.

Zvlášť důležité je chování Booking.com: search cena může být složena z více
pokojů, zatímco `/v1/price` je jedna rezervovatelná jednotka. Proto nástroj
porovnává `search` cenu s `/v1/price` pro přesné obsazení a označí případy, kdy
search cenu nelze získat jako jednu jednotku.

## Omezení

- Search vrací maximálně 40 výsledků na platformu a dotaz a nemá stránkování.
  Vzorek je průřez, ne úplný seznam.
- Lokalita se zadává názvem; okruh filtrujeme až lokálně podle souřadnic.
- Rozsah nabídky a seskupení jednotek jsou heuristiky. API nevrací inventář
  jednotek v domě.
- `totalPrice` nemusí obsahovat všechny daně a poplatky.
- Cache hit se stále účtuje.
- Nástroj nepočítá dobu chůze, jen vzdušnou vzdálenost.
- Výpadek upstreamu není totéž jako prázdný výsledek. Report to rozlišuje.

## Testy

```bash
python -m unittest discover -s tests -v
```

Testy nepotřebují API klíč. Pokrývají klasifikaci rozsahu, seskupení, deduplikaci,
výpočet kreditů a HTTP klienta včetně async `202` → `jobId` proti lokálnímu
mock serveru.

## Vizualizace pro 10 osob

Statická stránka je v `docs/` a je připravená pro GitHub Pages:

- `docs/index.html` — karty variant, mapa, filtry a graf ceny vs. vzdálenost.
- `docs/assets/` — CSS a JavaScript.
- `docs/data/pairs.js` — vygenerovaná data (načítají se přímo, bez serveru).

Data se generují z kombinací pro 10 osob (základ 15/10 km i širší sada pro UI):

```bash
python scripts/enrich_booking.py         # fotky a souřadnice Booking nemovitostí
python scripts/route_distances.py        # silniční vzdálenosti k lanovkám (OSRM)
python scripts/route_pair_distances.py   # silniční vzdálenosti mezi jednotkami
python scripts/combine_units.py
python scripts/combine_units.py --max-resort-km 25 --max-unit-km 1 \
  --max-pairs 150 --out data/trip_search/combos_2027-02-01_wide
python scripts/build_visualization.py
```

Na stránku jde pro každé středisko sada celých objektů a dvojic (jen do
3 500 € celkem): 40 dvojic v základním filtru (≤ 15 km po silnici k lanovce,
≤ 1 km mezi jednotkami) a další varianty pro rozšířený filtr do 25 km; plná data zůstávají v `data/trip_search/combos_2027-02-01/`
a `combos_2027-02-01_wide/`. Stránka je pro termín 1.–6. 2. 2027 (5 nocí), má chipy pro výběr více
středisek a posuvníky vzdáleností s výchozími hodnotami 15 km k lanovce
a 1 km mezi jednotkami.

Lokálně:

```bash
python3 -m http.server 8000 --directory docs
# otevři http://localhost:8000
```

GitHub Pages: v nastavení repozitáře zvol **Deploy from a branch**, branch `main`
a složku `/docs`. Soubor `docs/.nojekyll` je součástí, takže se nic nepředzpracovává.

## Lokální Airbnb bez API klíče

Pro doplnění nových středisek lze použít lokální `pyairbnb` (neoficiální, bez klíče;
Airbnb může scrapování blokovat nebo měnit).

```bash
python3 -m venv .venv-local
source .venv-local/bin/activate
pip install -r requirements-local.txt
python scripts/search_local_airbnb.py
python scripts/build_visualization.py
```

Skript ukládá výsledky do `data/trip_search/local_airbnb/` a vizualizace je bere
při dalším buildu. Pokrývá 12 areálů: Schladming (včetně Ramsau), Tauplitz,
Almenwelt Lofer, Hochkönig, Dachstein West, Skicircus Saalbach, Lungau,
Gastein, Obertauern, Nassfeld, Katschberg a Kreischberg/Lachtal. Nové oblasti
lze dohledat přes `--areas lofer,saalbach,gastein,lungau`. Hledá celý objekt pro 10 osob (minimum 4 ložnice) i menší
jednotky pro 2–8 osob, ze kterých jde skládat páry do 10 osob, v termínu
1. 2. – 5. 2. 2027 (4 noci) a navíc variantu 1. 2. – 6. 2. 2027 (5 nocí),
protože u části objektů vyjde celkově levněji; tato varianta se ukládá jako
`*_N_5n.json`.

## Lokální Booking přes skutečný prohlížeč

Booking blokuje headless prohlížeče AWS WAF challenge. Na tomto počítači funguje
**headful Chromium** s uloženou session. Vyžaduje lokální displej (nebo Xvfb);
na headless VPS to nepoběží bez dalšího nastavení.

```bash
python3 -m venv .venv-booking
source .venv-booking/bin/activate
pip install -r requirements-booking-local.txt
playwright install chromium
python scripts/search_local_booking.py
python scripts/build_visualization.py
```

Skript dočasně přepne `viajante` na `headless=False`, provede hledání pro 10 osob
(4 pokoje) i menší obsazenosti 2–8 osob v termínu 1. 2. – 5. 2. 2027 (4 noci)
a navíc pro 1. 2. – 6. 2. 2027 (5 nocí, uloženo jako `*_N_5n.json`), a uloží
JSON reporty do `data/trip_search/local_booking/`. Ceny jsou za celý pobyt;
vzdálenost od areálu Booking v kartách neuvádí. Jde o neoficiální scraping,
Booking může session nebo přístup kdykoli zablokovat.

## Kombinace pro 10 osob

Dvojice (4+6, 5+5, 3+7, 2+8) menších jednotek se skládají z výstupů obou
lokálních hledačů; trojice se neskládají:

```bash
python scripts/combine_units.py
```

Skript páruje jen jednotky ve stejném středisku a dodržuje:

- každá jednotka max. **15 km po silnici k nejbližší nástupní stanici lanovky** (`--max-resort-km`),
- jednotky ve dvojici max. **1 km od sebe po silnici** (`--max-unit-km`).

Nástupní stanice lanovek jsou v `scripts/local_units.py` (OpenStreetMap,
Overpass; dolní konec podle výšky z EU-DEM). Booking nemovitostem doplňuje
fotku a souřadnice `scripts/enrich_booking.py` (ze stránek výsledků, cache
`booking_enrichment.json`). Vzdálenosti k lanovkám počítá
`scripts/route_distances.py` a vzdálenosti mezi jednotkami
`scripts/route_pair_distances.py` přes OSRM (cache `road_distances.json` a
`road_pair_distances.json`).

Ceny jsou za celý pobyt 1.–6. 2. 2027 (5 nocí) a ukládají se do
`data/trip_search/combos_2027-02-01/` (`combos_5n.json`). Jednotky, které se
do stropu 3 500 € nevejdou ani s nejlevnějším možným doplňkem, se vyřazují už
při skládání; hotové varianty nad strop se zahazují také.
