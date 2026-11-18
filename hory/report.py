from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def _escape(value: Any) -> str:
    if value is None or value == "":
        return "—"
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _short(value: Any, length: int = 46) -> str:
    text = _escape(value)
    return text if len(text) <= length else text[: length - 1] + "…"


def _money(value: Any, currency: Any = None) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _escape(value)
    formatted = f"{number:,.0f}".replace(",", " ")
    return f"{formatted} {currency}" if currency else formatted


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.1f} %"
    except (TypeError, ValueError):
        return _escape(value)


def _flags(flags: list[str] | None, max_items: int = 4) -> str:
    if not flags:
        return "—"
    shown = [f"`{flag}`" for flag in flags[:max_items]]
    if len(flags) > max_items:
        shown.append(f"+{len(flags) - max_items}")
    return ", ".join(shown)


def _price_check_for(
    summary: dict[str, Any],
    candidate_key: str,
    label: str,
) -> dict[str, Any] | None:
    for check in summary.get("price_checks") or []:
        if check.get("candidate_key") == candidate_key and check.get("occupancy_label") == label:
            return check
    return None


def _verified_price_text(check: dict[str, Any] | None) -> str:
    if not check:
        return "—"
    error = check.get("error") or {}
    if error:
        return f"chyba: {_escape(error.get('code') or error.get('message'))}"
    quote = check.get("quote") or {}
    if not quote:
        return "—"
    currency = quote.get("currency")
    total = quote.get("totalPrice")
    basis = quote.get("priceBasis") or "?"
    return f"{_money(total, currency)} ({_escape(basis)})"


def build_markdown(summary: dict[str, Any]) -> str:
    config = summary.get("config") or {}
    run = summary.get("run") or {}
    account = summary.get("account") or {}
    answers = summary.get("answers") or {}
    properties = summary.get("properties") or []
    clusters = summary.get("clusters") or []
    price_checks = summary.get("price_checks") or []
    credits = summary.get("credits") or {}
    searches = summary.get("searches") or []
    in_radius = [prop for prop in properties if prop.get("in_radius", True)]
    outside = [prop for prop in properties if not prop.get("in_radius", True)]

    lines: list[str] = []
    add = lines.append

    add("# StayingAPI — ověření na malém vzorku")
    add("")
    add(f"- Běh: `{_escape(run.get('started_at'))}` → `{_escape(run.get('finished_at'))}`")
    add(f"- Výstup: `{_escape(run.get('run_dir'))}`")
    add(f"- Lokalita: **{_escape(config.get('location'))}**")
    center = config.get("center")
    if center:
        add(
            f"- Střed pro filtr: {center.get('lat')}, {center.get('lng')}; "
            f"okruh {config.get('radius_km')} km (vzdušnou čarou)"
        )
    else:
        add("- Střed pro filtr není znám; okruh se nefiltroval.")
    add(
        f"- Termín: **{_escape(config.get('check_in'))} → {_escape(config.get('check_out'))}** "
        f"({config.get('nights')} nocí)"
    )
    ages = config.get("child_ages") or []
    add(
        f"- Skupina: **{config.get('adults')} dospělých + {config.get('children')} dětí** "
        f"(věk v době pobytu: {', '.join(str(age) for age in ages) or '—'})"
    )
    add(
        f"- Platformy: {', '.join(config.get('platforms') or [])}; "
        f"limit {config.get('limit')} na platformu a dotaz; rooms {config.get('rooms', 1)}; "
        f"měna {config.get('currency')}"
    )
    add(
        f"- Klíč: **{_escape(account.get('key_env') or 'neznámý')}**; "
        f"rozpočet {config.get('max_credits')} kreditů"
    )
    if account.get("is_sandbox"):
        add("")
        add(
            "> **Pozor: sandbox.** Odpovědi jsou deterministické fixtures, ne skutečná data. "
            "Tento běh neodpovídá na otázky o reálné nabídce a nesmí být použit pro rozhodnutí."
        )
    data_quality = summary.get("data_quality") or {}
    if data_quality.get("all_failed"):
        add("")
        add(
            "> **Hledání selhalo na upstreamu.** Žádné search volání neproběhlo úspěšně. "
            "Tento report není důkaz, že v lokalitě není ubytování; data prostě nebyla "
            "doručena. Podrobnosti a requestId jsou níže."
        )
    add("")

    add("## Odpovědi na ověřovací otázky")
    add("")
    questions = [
        ("1. Je nabídka konkrétní apartmán, nebo celý apartmánový dům?", "q1_scope"),
        ("2. Vrací API kapacitu, polohu a použitelné identifikátory?", "q2_fields"),
        ("3. Lze cenu ověřit pro konkrétní rozdělení dospělých a dětí?", "q3_price_by_occupancy"),
        ("4. Lze rozlišit dostupné jednotky ve stejném domě?", "q4_units_in_same_house"),
        ("5. Kolik stojí jedno kompletní hledání v kreditech?", "q5_credit_cost"),
    ]
    add("| Otázka | Závěr |")
    add("|---|---|")
    for label, key in questions:
        answer = answers.get(key) or {}
        add(f"| {label} | **{_escape(answer.get('status'))}** |")
    add("")
    for label, key in questions:
        answer = answers.get(key) or {}
        add(f"### {label}")
        add("")
        add(f"**{_escape(answer.get('status'))}** — {_escape(answer.get('text'))}")
        add("")

    add("## Průběh hledání")
    add("")
    if searches:
        add("| Hledání | Obsazení | Vráceno | Kredity | Platformy | Stav | Chyba / requestId | Raw |")
        add("|---|---|---:|---:|---|---|---|---|")
        for search in searches:
            occupancy = search.get("occupancy") or {}
            occupancy_text = (
                f"{occupancy.get('adults', '?')}A + {occupancy.get('children', 0)}C"
            )
            platform_results = search.get("platform_results") or []
            platform_text = ", ".join(
                f"{item.get('platform')}:{item.get('status')}({item.get('count', 0)})"
                for item in platform_results
            )
            error = search.get("error") or {}
            warnings = search.get("warnings") or []
            status_text = "ok" if search.get("ok") else "chyba"
            if error:
                error_text = error.get("message") or error.get("code") or "error"
                if error.get("request_id") or search.get("request_id"):
                    error_text += f" ({error.get('request_id') or search.get('request_id')})"
            elif warnings:
                error_text = ", ".join(str(item) for item in warnings)
            else:
                error_text = ""
            add(
                f"| {_escape(search.get('label'))} | {occupancy_text} | "
                f"{search.get('count', 0)} | {search.get('credits', 0)} | "
                f"{_short(platform_text, 50)} | {status_text} | "
                f"{_short(error_text, 80)} | `{_escape(search.get('raw_file'))}` |"
            )
        add("")
    else:
        add("Žádné hledání neproběhlo.")
        add("")

    errors = data_quality.get("errors") or []
    if errors:
        add("### Chyby hledání")
        add("")
        for error in errors[:10]:
            request_id = error.get("request_id") or "—"
            add(
                f"- **{_escape(error.get('label') or error.get('key'))}**: "
                f"`{_escape(error.get('type'))}` / `{_escape(error.get('code'))}` — "
                f"{_escape(error.get('message'))} (requestId `{_escape(request_id)}`)"
            )
        if len(errors) > 10:
            add(f"- … a dalších {len(errors) - 10} chyb v `manifest.jsonl`.")
        add("")

    add("## Kandidáti a ceny")
    add("")
    if data_quality.get("all_failed"):
        add(
            "Search volání selhala, takže seznam kandidátů je prázdný. Nejde o potvrzení, "
            "že v lokalitě žádné ubytování není."
        )
    else:
        add(
            f"V okruhu je unikátních nabídek: {len(in_radius)}; mimo okruh: {len(outside)}. "
            "Tabulka ukazuje prvních 40 v okruhu; plný seznam je v `summary.json` a `candidates.csv`."
        )
    add("")
    if in_radius:
        add(
            "| Nabídka | Platforma | Typ | Rozsah (odhad) | Max | Lož. | Vzdálenost | "
            "Search cena | Cena pro celou skupinu | Poznámky |"
        )
        add("|---|---|---|---|---:|---:|---:|---|---|---|")
        for prop in in_radius[:40]:
            check = _price_check_for(summary, prop["key"], "full")
            flags = list(prop.get("flags") or [])
            if prop.get("cluster_id"):
                flags.append(f"cluster:{prop['cluster_id']}")
            add(
                f"| [{_short(prop.get('name'), 42)}]({_escape(prop.get('url'))}) | "
                f"{_escape(prop.get('platform'))} | {_escape(prop.get('property_type'))} | "
                f"{_escape(prop.get('scope'))} ({_escape(prop.get('scope_confidence'))}) | "
                f"{_escape(prop.get('max_occupancy'))} | {_escape(prop.get('bedrooms'))} | "
                f"{_escape(prop.get('distance_km'))} km | "
                f"{_money(prop.get('search_price_total'), prop.get('search_price_currency'))} | "
                f"{_verified_price_text(check)} | {_flags(flags)} |"
            )
        add("")
    else:
        if not data_quality.get("all_failed"):
            add("V okruhu nejsou žádné nabídky.")
        add("")

    add("## Detaily vybraných nabídek")
    add("")
    listing_probes = summary.get("listing_probes") or []
    if listing_probes:
        add("| Nabídka | Platforma | Identita | Max | Lož. | Koup. | Vybavení | Fotek | Poznámky |")
        add("|---|---|---|---:|---:|---:|---|---:|---|")
        for probe in listing_probes:
            detail = probe.get("detail") or {}
            error = probe.get("error") or {}
            identity = detail.get("identity") or {}
            resolved = identity.get("resolvedId") or identity.get("requestedId")
            amenities = detail.get("amenities") or []
            add(
                f"| {_short(detail.get('name') or probe.get('candidate_key'), 38)} | "
                f"{_escape(probe.get('platform'))} | {_escape(resolved)} | "
                f"{_escape(detail.get('max_occupancy'))} | {_escape(detail.get('bedrooms'))} | "
                f"{_escape(detail.get('bathrooms'))} | "
                f"{_short(', '.join(str(item) for item in amenities), 55)} | "
                f"{_escape(detail.get('images_count'))} | "
                f"{_escape(error.get('code') or error.get('message'))} |"
            )
        add("")
        add(
            "Identita je `resolvedId` z `/v1/listing`; pro Booking.com je potřeba `country`. "
            "Vybavení je canonical taxonomy, ne doslovný text platformy."
        )
    else:
        add("Detaily neproběhly.")
    add("")

    add("## Cenové ověření")
    add("")
    if price_checks:
        add("| Nabídka | Obsazení | Search cena | Cena z /v1/price | Vztah | Basis / flags |")
        add("|---|---|---|---|---|---|")
        for check in price_checks:
            quote = check.get("quote") or {}
            error = check.get("error") or {}
            occupancy = check.get("occupancy") or {}
            occupancy_text = (
                f"{occupancy.get('adults', '?')}A + {occupancy.get('children', 0)}C"
            )
            quote_text = (
                _money(quote.get("totalPrice"), quote.get("currency"))
                if quote and not error
                else f"chyba: {_escape(error.get('code') or error.get('message'))}"
            )
            search_price = check.get("search_price") or {}
            basis_flags = []
            if quote.get("priceBasis"):
                basis_flags.append(str(quote.get("priceBasis")))
            basis_flags.extend(check.get("flags") or [])
            add(
                f"| {_short(check.get('name'), 38)} | {occupancy_text} | "
                f"{_money(search_price.get('totalPrice'), search_price.get('currency'))} | "
                f"{quote_text} | {_escape(check.get('relation'))} "
                f"({_pct(check.get('delta_pct'))}) | {_flags(basis_flags, 5)} |"
            )
        add("")
    else:
        add("Cenové dotazy neproběhly.")
        add("")

    add("## Seskupení podle názvu a polohy")
    add("")
    multi = [cluster for cluster in clusters if cluster.get("size", 0) > 1]
    if multi:
        add("| Cluster | Velikost | Platformy | Rozpětí | Interpretace | Členy |")
        add("|---|---:|---|---:|---|---|")
        for cluster in multi:
            members = "; ".join(
                f"{member.get('platform')}:{member.get('platform_listing_id')} "
                f"({_short(member.get('name'), 30)})"
                for member in cluster.get("members") or []
            )
            add(
                f"| {_escape(cluster.get('cluster_id'))} | {cluster.get('size')} | "
                f"{_escape(', '.join(cluster.get('platforms') or []))} | "
                f"{cluster.get('span_m')} m | {_escape(cluster.get('interpretation'))} | "
                f"{_short(members, 100)} |"
            )
        add("")
        add(
            "Seskupení je heuristika podle názvu a souřadnic. Neznamená, že jde o stejnou "
            "rezervovatelnou jednotku, ani že jsou jednotky v domě dostupné společně."
        )
    else:
        add("Na vzorku nejsou žádné blízké nabídky se podobným názvem.")
    add("")

    add("## Kredity")
    add("")
    add(
        f"- Dostupné před během: **{_escape(account.get('available_before'))}**; "
        f"po běhu: **{_escape(account.get('available_after'))}**"
    )
    add(
        f"- Utraceno podle `meta.creditsCharged`: **{credits.get('total', 0)}** "
        f"(hledání {credits.get('search', 0)}, listing {credits.get('listing', 0)}, "
        f"ceny {credits.get('price', 0)})"
    )
    add(
        f"- Worst-case jednoho search dotazu při {len(config.get('platforms') or [])} "
        f"platformách a limitu {config.get('limit')}: **{credits.get('search_worst_case', 0)}** kreditů"
    )
    add(
        f"- Worst-case celého probe ({credits.get('search_count', 0)} dotazů + ověření): "
        f"**{credits.get('probe_worst_case', 0)}** kreditů"
    )
    add("")
    if searches:
        add("| Hledání | Vráceno | Kredity |")
        add("|---|---:|---:|")
        for item in credits.get("per_search") or []:
            add(f"| {_escape(item.get('label'))} | {item.get('count', 0)} | {item.get('credits', 0)} |")
        add("")
    add(
        "Vzorec: search účtuje min. 5 kreditů za platformu, dále Airbnb 2 za výsledek, "
        "Booking.com a Vrbo 1 za výsledek; Google Hotels 15 za stránku do 20 hotelů. "
        "`/v1/listing` stojí 3 (Vrbo 15), `/v1/price` 3. Cache hit se stále účtuje."
    )
    add("")
    skips = summary.get("budget_skips") or []
    if skips:
        add("### Zastaveno rozpočtem")
        add("")
        for skip in skips:
            add(f"- {_escape(skip)}")
        add("")

    add("## Neověřené a chybějící údaje")
    add("")
    flag_counts: dict[str, int] = {}
    for prop in properties:
        for flag in prop.get("flags") or []:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
    for check in price_checks:
        for flag in check.get("flags") or []:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
    for probe in summary.get("listing_probes") or []:
        for warning in probe.get("warnings") or []:
            flag_counts[str(warning)] = flag_counts.get(str(warning), 0) + 1
    for search in searches:
        for warning in search.get("warnings") or []:
            flag_counts[str(warning)] = flag_counts.get(str(warning), 0) + 1
    if data_quality.get("all_failed"):
        add("Data nejsou k dispozici; žádné signály o nabídce nelze vyhodnotit.")
        add("")
    elif flag_counts:
        add("| Signál | Výskytů | Význam |")
        add("|---|---:|---|")
        meanings = {
            "capacity_unknown": "API nevrátilo kapacitu; nelze potvrdit, že se skupina vejde.",
            "building_name_without_unit_number": "Název v plurálu bez čísla jednotky; může jít o budovu.",
            "capacity_below_group": "Kapacita nabídky je nižší než skupina.",
            "search_price_may_be_multi_room": "Search cena existuje i při nízké kapacitě; může jít o více pokojů.",
            "search_price_missing": "Search výsledek nemá cenu.",
            "location_unknown": "Chybí souřadnice; okruh ani vzdálenost nelze ověřit.",
            "currency_passthrough": "Cena je v jiné měně, než byla požadována; bez FX převodu.",
            "price_is_estimate": "Cena je odhad z noční sazby, ne garantovaný total.",
            "taxes_may_be_extra": "Daně mohou být přičteny při rezervaci.",
            "fees_not_itemized": "Platforma neuvádí poplatky rozepsané.",
            "price_basis_unknown": "Chybí priceBasis; nelze určit, co cena zahrnuje.",
            "search_price_but_single_unit_no_availability": "Search měl cenu, ale /v1/price pro celou skupinu vrátil no_availability.",
            "price_delta_over_10pct": "Cena z /v1/price se liší od search ceny o více než 10 %.",
            "price_delta_within_10pct": "Cena z /v1/price je blízko search ceně.",
            "price_may_exclude_taxes": "Platforma uvedla cenu, ke které mohou být přidány daně.",
            "price_unverified": "Cena je neověřený odhad (typicky Vrbo).",
            "partial_details": "Některé detaily chybí.",
            "amenity_post_filtered": "Filtrování vybavení proběhlo až po stažení.",
            "post_filter_empty": "Po filtrování vybavení nezůstaly výsledky.",
            "no_calendar": "Vrbo nevrátilo kalendář.",
            "price_resolved_via_search": "Cena byla dohledána přes search.",
        }
        for flag, count in sorted(flag_counts.items(), key=lambda item: (-item[1], item[0])):
            add(f"| `{_escape(flag)}` | {count} | {meanings.get(flag, '—')} |")
        add("")
    else:
        add("Žádné zvláštní signály.")
        add("")

    add("## Limity tohoto ověření")
    add("")
    add(
        "- Search vrací maximálně 40 výsledků na platformu a dotaz a nemá stránkování. "
        "Vzorek je proto průřez, ne úplný seznam."
    )
    add(
        "- Lokalita se zadává názvem, ne souřadnicemi. Okruh filtrujeme až lokálně; "
        "výsledky bez souřadnic zůstávají označené."
    )
    add(
        "- Rozsah nabídky (jednotka vs celý dům) a seskupení jednotek jsou heuristiky. "
        "API nevrací inventář jednotek v domě."
    )
    add(
        "- `totalPrice` nemusí obsahovat všechny daně a poplatky. U Booking.com může být "
        "search cena složena z více pokojů, zatímco `/v1/price` je jedna jednotka."
    )
    add(
        "- Živé požadavky mohou běžet minuty a vracet 202 s úlohou. Skript čeká a ukládá "
        "až dokončený výsledek."
    )
    add(
        "- Výpadek upstreamu (`all_actors_failed`) není totéž jako prázdný výsledek. "
        "Report to rozlišuje; selhaná volání jsou zdarma."
    )
    add("")

    add("## Doporučení pro pokračování")
    add("")
    q1 = answers.get("q1_scope") or {}
    q4 = answers.get("q4_units_in_same_house") or {}
    if data_quality.get("all_failed"):
        request_ids = ", ".join(
            f"`{error.get('request_id')}`"
            for error in (data_quality.get("errors") or [])[:3]
            if error.get("request_id")
        ) or "—"
        add(
            "Tento běh neříká nic o nabídce: žádné search volání neuspělo. "
            "Nejde o důkaz, že StayingAPI neumí hledat nebo že v lokalitě není ubytování. "
            f"Selhaná volání byla zdarma (0 kreditů). RequestId pro podporu: {request_ids}. "
            "Zkuste běh později zopakovat, ideálně nejdřív jedním malým dotazem "
            "(`--platforms booking --limit 5 --max-sub-searches 0 --detail-candidates 0`). "
            "Pokud se `all_actors_failed` opakuje, kontaktujte StayingAPI podporu s requestId "
            "a časem běhu; zkontrolujte také status.stayingapi.com a changelog."
        )
    elif q1.get("status") in {"ČÁSTEČNĚ", "NELZE URČIT"} or q4.get("status") not in {"ANO"}:
        add(
            "Na tomto vzorku nelze potvrdit, že StayingAPI samo stačí pro spolehlivé "
            "kombinování více samostatných jednotek ve stejném domě. Pro celý objekt a "
            "kombinace samostatných objektů je použitelné, pokud `/v1/price` potvrdí "
            "kapacitu pro konkrétní obsazení. Pro variantu více jednotek v jednom domě "
            "je potřeba další zdroj dat nebo ruční potvrzení."
        )
    else:
        add(
            "Vzorek podporuje pokračování: celý objekt i samostatné objekty lze ověřovat "
            "přes search + price. Vztahy mezi jednotkami v domě stále berte jako neověřené."
        )
    add("")
    if data_quality.get("all_failed"):
        add(
            "Bod 2 má smysl až po úspěšném live běhu; tento běh data o nabídce nepřinesl."
        )
    else:
        add(
            "Další krok podle plánu: bod 2 — vstupní formulář a datový model budova / "
            "rezervovatelná jednotka / nabídka na platformě. Nejdřív ale nechte proběhnout "
            "live běh s reálným klíčem a zkontrolujte odpovědi výše."
        )
    add("")

    add("## Raw data")
    add("")
    add(
        "Kompletní odpovědi jsou v `raw/`, seznam volání s parametry a kredity v "
        "`manifest.jsonl`, strukturovaný výsledek v `summary.json` a tabulka kandidátů "
        "v `candidates.csv`."
    )
    add("")
    return "\n".join(lines)


def write_candidates_csv(summary: dict[str, Any], path: str | Path) -> None:
    fields = [
        "key",
        "name",
        "platform",
        "platform_listing_id",
        "property_type",
        "scope",
        "scope_confidence",
        "max_occupancy",
        "bedrooms",
        "bathrooms",
        "distance_km",
        "in_radius",
        "cluster_id",
        "search_price_total",
        "search_price_currency",
        "flags",
        "url",
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for prop in summary.get("properties") or []:
            row = {field: prop.get(field) for field in fields}
            row["flags"] = ",".join(prop.get("flags") or [])
            writer.writerow(row)


def write_summary_json(summary: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
