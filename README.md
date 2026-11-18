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

## Vizualizace dvojic

Statická stránka je v `docs/` a je připravená pro GitHub Pages:

- `docs/index.html` — karty dvojic, mapa, filtr a graf ceny vs. vzdálenost.
- `docs/assets/` — CSS a JavaScript.
- `docs/data/pairs.js` — vygenerovaná data (načítají se přímo, bez serveru).

Data se generují z raw Airbnb odpovědí:

```bash
python scripts/build_visualization.py
```

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
při dalším buildu. Hledá obsazení 2–10 osob s minimem ložnic podle velikosti
skupiny; stránka z toho skládá dvojice, trojice i čtveřice pro 12 osob.

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

Skript dočasně přepne `viajante` na `headless=False`, provede hledání pro 7 osob
(3 pokoje) a 5 osob (2 pokoje), uloží JSON reporty do
`data/trip_search/local_booking/`. Ceny jsou za celý pobyt; vzdálenost od areálu
Booking v kartách neuvádí. Jde o neoficiální scraping, Booking může session
nebo přístup kdykoli zablokovat.
