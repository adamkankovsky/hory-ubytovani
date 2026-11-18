from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import analysis, report
from .staying import (
    StayingAPIError,
    StayingClient,
    RawStore,
    load_dotenv,
    now_iso,
)

DEFAULT_LOCATION = "Schladming, Austria"
DEFAULT_CHECK_IN = "2027-07-03"
DEFAULT_NIGHTS = 4
DEFAULT_ADULTS = 12
DEFAULT_CHILDREN_AGES = "6,9,12"
DEFAULT_PLATFORMS = "airbnb,booking"
DEFAULT_CURRENCY = "EUR"
DEFAULT_LIMIT = 10
DEFAULT_MAX_CREDITS = 250
DEFAULT_DETAIL_CANDIDATES = 6
DEFAULT_SPLIT_PROBES = 2
DEFAULT_RADIUS_KM = 20.0
SCHLADMING_CENTER = {"lat": 47.3944, "lng": 13.6878}
ALLOWED_PLATFORMS = {"airbnb", "booking", "vrbo", "google"}


@dataclass
class Budget:
    limit: int
    spent: int = 0
    skips: list[str] = field(default_factory=list)

    def allow(self, cost: int, reserve: int = 0) -> bool:
        return self.spent + cost + reserve <= self.limit


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", file=sys.stderr, flush=True)


def parse_ages(value: str) -> list[int]:
    if not value.strip():
        return []
    ages = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        age = int(part)
        if age < 0 or age > 17:
            raise ValueError(f"Věk dítěte musí být 0–17, dostal jsem {age}")
        ages.append(age)
    return ages


def parse_platforms(value: str) -> list[str]:
    platforms = []
    for part in value.split(","):
        platform = part.strip().lower()
        if not platform:
            continue
        if platform not in ALLOWED_PLATFORMS:
            raise ValueError(
                f"Neznámá platforma {platform!r}; povolené: {', '.join(sorted(ALLOWED_PLATFORMS))}"
            )
        if platform not in platforms:
            platforms.append(platform)
    if not platforms:
        raise ValueError("Musí být zadaná alespoň jedna platforma")
    return platforms


def parse_center(value: str | None, location: str) -> dict[str, float] | None:
    if value:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 2:
            raise ValueError("--center musí být ve formátu 'lat,lng'")
        center = {"lat": float(parts[0]), "lng": float(parts[1])}
        if not (-90 <= center["lat"] <= 90 and -180 <= center["lng"] <= 180):
            raise ValueError("Souřadnice --center jsou mimo rozsah")
        return center
    if "schladming" in location.lower():
        return dict(SCHLADMING_CENTER)
    return None


def _occupancy_label(adults: int, children: int) -> str:
    return f"{adults}A" + (f"+{children}C" if children else "")


def _sub_spec(
    key: str,
    label: str,
    adults: int,
    children: int,
    ages: list[int],
    *,
    limit: int,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "adults": adults,
        "children": children,
        "child_ages": ages[:children],
        "limit": limit,
    }


def auto_sub_specs(
    adults: int,
    children: int,
    ages: list[int],
    *,
    limit: int,
    max_items: int = 5,
) -> list[dict[str, Any]]:
    priority = [(8, 2), (6, 1), (4, 2), (4, 0), (2, 0), (6, 0)]
    specs: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    group_total = adults + children
    for target_adults, target_children in priority:
        sub_adults = max(1, min(adults, target_adults))
        sub_children = max(0, min(children, target_children))
        key_pair = (sub_adults, sub_children)
        if key_pair in seen:
            continue
        if sub_adults + sub_children >= group_total:
            continue
        seen.add(key_pair)
        key = f"sub_{sub_adults}a_{sub_children}c"
        specs.append(
            _sub_spec(
                key,
                f"menší: {_occupancy_label(sub_adults, sub_children)}",
                sub_adults,
                sub_children,
                ages,
                limit=limit,
            )
        )
        if len(specs) >= max_items:
            break
    return specs


def parse_sub_specs(value: str, adults: int, children: int, ages: list[int], *, limit: int) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    group_total = adults + children
    for part in value.split(","):
        part = part.strip().upper()
        if not part:
            continue
        match = re.fullmatch(r"(\d+)A(?:\+(\d+)C)?", part)
        if not match:
            raise ValueError(f"Neplatné obsazení {part!r}; čekám např. 8A+2C nebo 4A")
        sub_adults = int(match.group(1))
        sub_children = int(match.group(2) or 0)
        if sub_adults < 1 or sub_adults > adults:
            raise ValueError(f"Obsazení {part}: dospělých musí být 1–{adults}")
        if sub_children < 0 or sub_children > children:
            raise ValueError(f"Obsazení {part}: dětí musí být 0–{children}")
        if sub_adults + sub_children >= group_total:
            raise ValueError(f"Obsazení {part} není menší než celá skupina")
        key = f"sub_{sub_adults}a_{sub_children}c"
        specs.append(
            _sub_spec(
                key,
                f"menší: {_occupancy_label(sub_adults, sub_children)}",
                sub_adults,
                sub_children,
                ages,
                limit=limit,
            )
        )
    if not specs:
        raise ValueError("--sub-occupancies neobsahuje žádné platné obsazení")
    return specs


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    location = args.location.strip()
    if not location:
        raise ValueError("Lokalita nesmí být prázdná")

    check_in = date.fromisoformat(args.check_in)
    if check_in < date.today():
        raise ValueError(f"Příjezd {check_in} je v minulosti")
    if args.nights < 1 or args.nights > 30:
        raise ValueError("Délka pobytu musí být 1–30 nocí")
    check_out = check_in + timedelta(days=args.nights)

    if args.adults < 1:
        raise ValueError("Počet dospělých musí být alespoň 1")
    ages = parse_ages(args.children)
    children = len(ages)
    if args.adults + children < 2:
        raise ValueError("Skupina musí mít alespoň 2 osoby")

    platforms = parse_platforms(args.platforms)
    currency = args.currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Měna musí být třípísmenný ISO kód, např. EUR")
    if args.limit < 1 or args.limit > 40:
        raise ValueError("--limit musí být 1–40")
    if args.rooms < 1 or args.rooms > 20:
        raise ValueError("--rooms musí být 1–20")
    if args.max_credits <= 0:
        raise ValueError("--max-credits musí být kladné")
    if args.detail_candidates < 0 or args.split_probes < 0:
        raise ValueError("Počty kandidátů nesmí být záporné")
    if args.max_sub_searches < 0:
        raise ValueError("--max-sub-searches nesmí být záporné")
    if args.timeout <= 0:
        raise ValueError("--timeout musí být kladný")

    center = parse_center(args.center, location)
    if args.radius_km <= 0:
        raise ValueError("--radius-km musí být kladný")

    whole_spec = _sub_spec(
        "whole",
        "celá skupina",
        args.adults,
        children,
        ages,
        limit=args.limit,
    )
    if args.sub_occupancies:
        sub_specs = parse_sub_specs(
            args.sub_occupancies,
            args.adults,
            children,
            ages,
            limit=args.limit,
        )
    else:
        sub_specs = auto_sub_specs(
            args.adults,
            children,
            ages,
            limit=args.limit,
            max_items=args.max_sub_searches,
        )

    specs = [whole_spec, *sub_specs]
    for spec in specs:
        params = {
            "location": location,
            "checkIn": check_in.isoformat(),
            "checkOut": check_out.isoformat(),
            "adults": spec["adults"],
            "children": spec["children"],
            "platforms": ",".join(platforms),
            "limit": args.limit,
            "rooms": args.rooms,
            "currency": currency,
        }
        if spec["children"]:
            params["childAges"] = list(spec["child_ages"])
        spec["params"] = params

    detail_reserve = args.detail_candidates * 3 * 2 + args.split_probes * 2 * 3
    if "vrbo" in platforms:
        detail_reserve += 12

    return {
        "location": location,
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "nights": args.nights,
        "adults": args.adults,
        "children": children,
        "child_ages": ages,
        "platforms": platforms,
        "currency": currency,
        "limit": args.limit,
        "rooms": args.rooms,
        "max_credits": args.max_credits,
        "detail_candidates": args.detail_candidates,
        "split_probes": args.split_probes,
        "radius_km": args.radius_km,
        "center": center,
        "allow_sandbox": args.allow_sandbox,
        "sub_occupancies": args.sub_occupancies,
        "max_sub_searches": args.max_sub_searches,
        "detail_reserve": detail_reserve,
        "search_specs": specs,
        "min_interval": args.min_interval,
        "timeout": args.timeout,
        "continue_on_upstream_error": args.continue_on_upstream_error,
    }


def print_plan(config: dict[str, Any]) -> None:
    platforms = config["platforms"]
    limit = config["limit"]
    search_worst = analysis.search_worst_case(platforms, limit)
    total_search = search_worst * len(config["search_specs"])
    detail_reserve = config["detail_reserve"]
    print("Plán (bez volání API):")
    print(
        f"  Lokalita: {config['location']}; termín {config['check_in']} → {config['check_out']} "
        f"({config['nights']} nocí)"
    )
    print(
        f"  Skupina: {config['adults']} dospělých + {config['children']} dětí "
        f"(věk {config['child_ages']})"
    )
    print(
        f"  Platformy: {', '.join(platforms)}; limit {limit}/platformu; "
        f"rooms {config['rooms']}; měna {config['currency']}"
    )
    print("")
    print("  Hledání:")
    for spec in config["search_specs"]:
        print(
            f"    - {spec['label']}: {spec['adults']} dospělých + {spec['children']} dětí "
            f"(worst-case {search_worst} kr.)"
        )
    print(
        f"  Detaily: {config['detail_candidates']} kandidátů × listing + cena, "
        f"{config['split_probes']} kandidáti × 2 menší obsazení"
    )
    print("")
    print(f"  Worst-case hledání: {total_search} kr.")
    print(f"  Rezerva na detaily: {detail_reserve} kr.")
    total_worst = total_search + detail_reserve
    print(f"  Worst-case celkem: {total_worst} kr.")
    print(f"  Rozpočet: {config['max_credits']} kr. (skutečný strop se zkontroluje proti účtu)")
    if total_worst > config["max_credits"]:
        print(
            "  Pozor: worst-case překračuje rozpočet; část dotazů bude za běhu přeskočena. "
            "Sniž --limit, --detail-candidates, --split-probes nebo počet obsazení."
        )
    print("")
    print("  Dry-run nic nezapisuje a nepotřebuje klíč. Pro reálný běh nastav STAYINGAPI_KEY.")
    print("  Sandbox data nejsou skutečná; pro ně je potřeba --allow-sandbox.")


def _search_worst_for(config: dict[str, Any]) -> int:
    return analysis.search_worst_case(config["platforms"], config["limit"])


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")[:60] or "item"


def _price_params(
    config: dict[str, Any],
    candidate: dict[str, Any],
    occupancy: dict[str, Any],
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "platform": candidate.get("platform"),
        "listingId": candidate.get("platform_listing_id"),
        "checkIn": config["check_in"],
        "checkOut": config["check_out"],
        "adults": occupancy["adults"],
        "children": occupancy["children"],
        "currency": config["currency"],
    }
    if occupancy["children"]:
        params["childAges"] = list(occupancy["child_ages"])
    country = (candidate.get("location") or {}).get("country")
    if candidate.get("platform") == "booking" and country:
        params["country"] = str(country).lower()
    return params


def _listing_params(
    config: dict[str, Any],
    candidate: dict[str, Any],
    occupancy: dict[str, Any],
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "checkIn": config["check_in"],
        "checkOut": config["check_out"],
        "adults": occupancy["adults"],
        "children": occupancy["children"],
        "currency": config["currency"],
    }
    if occupancy["children"]:
        params["childAges"] = list(occupancy["child_ages"])
    country = (candidate.get("location") or {}).get("country")
    if candidate.get("platform") == "booking" and country:
        params["country"] = str(country).lower()
    return params


def _full_occupancy(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "adults": config["adults"],
        "children": config["children"],
        "child_ages": list(config["child_ages"]),
    }


def _split_occupancies(config: dict[str, Any]) -> list[dict[str, Any]]:
    adults = config["adults"]
    children = config["children"]
    ages = config["child_ages"]
    candidates = [
        (max(1, min(adults, adults - 4)), min(children, 2)),
        (max(1, min(adults, 4)), min(children, 1)),
    ]
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    group_total = adults + children
    for sub_adults, sub_children in candidates:
        if sub_adults + sub_children >= group_total:
            continue
        key = (sub_adults, sub_children)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "label": f"split_{sub_adults}a_{sub_children}c",
                "adults": sub_adults,
                "children": sub_children,
                "child_ages": ages[:sub_children],
            }
        )
    return result


def _select_candidates(
    properties: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    limit = int(config["detail_candidates"])
    in_radius = [
        prop
        for prop in properties
        if prop.get("in_radius", True)
        and prop.get("platform")
        and prop.get("platform_listing_id")
    ]
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    selected_clusters: set[str] = set()

    def price_value(prop: dict[str, Any]) -> float:
        try:
            return float(prop.get("search_price_total"))
        except (TypeError, ValueError):
            return 1e12

    def add(prop: dict[str, Any], *, allow_cluster_duplicate: bool = False) -> bool:
        if len(selected) >= limit:
            return False
        key = prop["key"]
        if key in selected_keys:
            return False
        cluster = prop.get("cluster_id")
        if cluster and cluster in selected_clusters and not allow_cluster_duplicate:
            return False
        selected.append(prop)
        selected_keys.add(key)
        if cluster:
            selected_clusters.add(cluster)
        return True

    suspicious = sorted(
        [
            prop
            for prop in in_radius
            if "search_price_may_be_multi_room" in (prop.get("flags") or [])
            or "capacity_below_group" in (prop.get("flags") or [])
        ],
        key=price_value,
    )
    for prop in suspicious[:2]:
        add(prop)

    whole_props = sorted(
        [
            prop
            for prop in in_radius
            if prop.get("scope") == "whole_property" and prop.get("capacity_ok")
        ],
        key=price_value,
    )
    for prop in whole_props[:2]:
        add(prop)

    whole_results = sorted(
        [prop for prop in in_radius if prop.get("has_whole_observation")],
        key=price_value,
    )
    for prop in whole_results[:2]:
        add(prop)

    sub_large = sorted(
        [prop for prop in in_radius if not prop.get("has_whole_observation")],
        key=lambda prop: (
            -(int(prop["max_occupancy"]) if prop.get("max_occupancy") is not None else 0),
            price_value(prop),
        ),
    )
    for prop in sub_large[:2]:
        add(prop)

    remaining = sorted(
        in_radius,
        key=lambda prop: (
            price_value(prop),
            prop.get("distance_km") if prop.get("distance_km") is not None else 9999,
        ),
    )
    for prop in remaining:
        if len(selected) >= limit:
            break
        add(prop)

    if len(selected) < limit:
        for prop in remaining:
            if len(selected) >= limit:
                break
            add(prop, allow_cluster_duplicate=True)

    return selected


def _record_from_call(
    spec: dict[str, Any] | None,
    result,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "spec": spec,
        "envelope": result.payload if result.ok else None,
        "error": result.error.to_dict() if result.error else None,
        "raw_file": result.raw_file,
        "credits": result.credits,
        "duration_s": result.duration_s,
        "job": result.job,
        "fatal": result.fatal,
        "abort": False,
    }
    if extra:
        record.update(extra)
    return record


def _skipped_record(
    *,
    spec: dict[str, Any] | None,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "spec": spec,
        "envelope": None,
        "error": {"code": "budget_skipped", "message": reason},
        "raw_file": None,
        "credits": 0,
        "duration_s": 0.0,
        "job": None,
        "fatal": False,
        "abort": False,
    }
    if extra:
        record.update(extra)
    return record


def _execute_searches(
    client: StayingClient,
    config: dict[str, Any],
    budget: Budget,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    worst = _search_worst_for(config)
    reserve = int(config["detail_reserve"])
    for index, spec in enumerate(config["search_specs"], start=1):
        label = spec["label"]
        if not budget.allow(worst, reserve):
            reason = (
                f"{label}: přeskočeno, rozpočet {budget.limit} kr. by nestačil na "
                f"worst-case {worst} + rezervu {reserve}"
            )
            budget.skips.append(reason)
            log(f"  {reason}")
            records.append(_skipped_record(spec=spec, reason=reason))
            continue
        log(
            f"Hledání {index}/{len(config['search_specs'])}: {label} "
            f"({spec['adults']}A+{spec['children']}C)"
        )
        result = client.call(
            "/v1/search",
            spec["params"],
            role=f"search_{spec['key']}",
        )
        budget.spent = client.spent_credits
        record = _record_from_call(spec, result)
        records.append(record)
        if result.ok:
            data = result.data
            count = len(data) if isinstance(data, list) else 0
            meta = result.meta
            log(
                f"  vráceno {count}, {result.credits} kr., "
                f"cached={meta.get('cached')}, partial={meta.get('partial')}"
            )
        else:
            error = result.error
            log(f"  chyba: {error.code or error.status} — {error}")
            upstream_failure = (
                error.type == "upstream_unavailable"
                or error.code in {"all_actors_failed", "upstream_timeout"}
            )
            if upstream_failure and not config.get("continue_on_upstream_error"):
                record["abort"] = True
                log(
                    "  upstream je nedostupný; zastavuji hledání. "
                    "Další dotazy by jen čekaly na circuit breaker. "
                    "Pokud chcete zkusit všechny, použijte --continue-on-upstream-error."
                )
                break
        if result.fatal:
            log("  fatální chyba, zastavuji hledání")
            break
    return records


def _execute_details(
    client: StayingClient,
    config: dict[str, Any],
    budget: Budget,
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    listing_records: list[dict[str, Any]] = []
    price_records: list[dict[str, Any]] = []
    full = _full_occupancy(config)

    for index, candidate in enumerate(candidates, start=1):
        listing_cost = analysis.listing_cost(str(candidate.get("platform") or ""))
        if budget.allow(listing_cost):
            log(
                f"Detail {index}/{len(candidates)}: {candidate.get('name')} "
                f"[{candidate.get('platform')}:{candidate.get('platform_listing_id')}]"
            )
            path = (
                f"/v1/listing/{quote(str(candidate.get('platform')), safe='')}/"
                f"{quote(str(candidate.get('platform_listing_id')), safe='')}"
            )
            result = client.call(
                path,
                _listing_params(config, candidate, full),
                role=f"listing_{_safe_key(candidate['key'])}",
            )
            budget.spent = client.spent_credits
            listing_records.append(
                _record_from_call(
                    None,
                    result,
                    extra={
                        "candidate_key": candidate["key"],
                        "platform": candidate.get("platform"),
                        "listing_id": candidate.get("platform_listing_id"),
                        "params": _listing_params(config, candidate, full),
                    },
                )
            )
            if not result.ok:
                log(f"  listing chyba: {result.error.code or result.error.status}")
        else:
            reason = f"listing {candidate['key']}: přeskočeno rozpočtem"
            budget.skips.append(reason)
            listing_records.append(
                _skipped_record(
                    spec=None,
                    reason=reason,
                    extra={
                        "candidate_key": candidate["key"],
                        "platform": candidate.get("platform"),
                        "listing_id": candidate.get("platform_listing_id"),
                        "params": _listing_params(config, candidate, full),
                    },
                )
            )

        if budget.allow(3):
            result = client.call(
                "/v1/price",
                _price_params(config, candidate, full),
                role=f"price_{_safe_key(candidate['key'])}_full",
            )
            budget.spent = client.spent_credits
            price_records.append(
                _record_from_call(
                    None,
                    result,
                    extra={
                        "candidate_key": candidate["key"],
                        "label": "full",
                        "occupancy": full,
                        "platform": candidate.get("platform"),
                        "listing_id": candidate.get("platform_listing_id"),
                        "params": _price_params(config, candidate, full),
                    },
                )
            )
            if not result.ok:
                log(f"  cena full chyba: {result.error.code or result.error.status}")
        else:
            reason = f"cena full {candidate['key']}: přeskočeno rozpočtem"
            budget.skips.append(reason)
            price_records.append(
                _skipped_record(
                    spec=None,
                    reason=reason,
                    extra={
                        "candidate_key": candidate["key"],
                        "label": "full",
                        "occupancy": full,
                        "platform": candidate.get("platform"),
                        "listing_id": candidate.get("platform_listing_id"),
                        "params": _price_params(config, candidate, full),
                    },
                )
            )

    for candidate in candidates[: int(config["split_probes"])]:
        for occupancy in _split_occupancies(config):
            if not budget.allow(3):
                reason = f"cena {occupancy['label']} {candidate['key']}: přeskočeno rozpočtem"
                budget.skips.append(reason)
                price_records.append(
                    _skipped_record(
                        spec=None,
                        reason=reason,
                        extra={
                            "candidate_key": candidate["key"],
                            "label": occupancy["label"],
                            "occupancy": occupancy,
                            "platform": candidate.get("platform"),
                            "listing_id": candidate.get("platform_listing_id"),
                            "params": _price_params(config, candidate, occupancy),
                        },
                    )
                )
                continue
            log(
                f"Cena {occupancy['label']}: {candidate.get('name')} "
                f"({occupancy['adults']}A+{occupancy['children']}C)"
            )
            result = client.call(
                "/v1/price",
                _price_params(config, candidate, occupancy),
                role=f"price_{_safe_key(candidate['key'])}_{occupancy['label']}",
            )
            budget.spent = client.spent_credits
            price_records.append(
                _record_from_call(
                    None,
                    result,
                    extra={
                        "candidate_key": candidate["key"],
                        "label": occupancy["label"],
                        "occupancy": occupancy,
                        "platform": candidate.get("platform"),
                        "listing_id": candidate.get("platform_listing_id"),
                        "params": _price_params(config, candidate, occupancy),
                    },
                )
            )
            if not result.ok:
                log(f"  cena chyba: {result.error.code or result.error.status}")

    return listing_records, price_records


def _search_summaries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for record in records:
        spec = record.get("spec") or {}
        envelope = record.get("envelope")
        meta = (envelope or {}).get("meta") or {}
        data = (envelope or {}).get("data")
        summaries.append(
            {
                "key": spec.get("key"),
                "label": spec.get("label"),
                "occupancy": {
                    "adults": spec.get("adults"),
                    "children": spec.get("children"),
                    "child_ages": spec.get("child_ages"),
                },
                "params": spec.get("params"),
                "ok": envelope is not None and not record.get("error"),
                "count": len(data) if isinstance(data, list) else 0,
                "credits": int(record.get("credits") or 0),
                "platform_results": meta.get("platformResults") or [],
                "warnings": meta.get("warnings") or [],
                "cached": meta.get("cached"),
                "partial": meta.get("partial"),
                "error": record.get("error"),
                "raw_file": record.get("raw_file"),
                "request_id": meta.get("requestId")
                or ((record.get("error") or {}).get("request_id")),
                "duration_s": record.get("duration_s"),
            }
        )
    return summaries


def _listing_summaries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for record in records:
        envelope = record.get("envelope")
        data = (envelope or {}).get("data")
        meta = (envelope or {}).get("meta") or {}
        detail = None
        if isinstance(data, dict):
            detail = {
                "name": data.get("name"),
                "property_type": data.get("propertyType"),
                "max_occupancy": data.get("maxOccupancy"),
                "bedrooms": data.get("bedrooms"),
                "bathrooms": data.get("bathrooms"),
                "amenities": data.get("amenities") or [],
                "host": data.get("host"),
                "identity": data.get("identity"),
                "price": data.get("price"),
                "images_count": len(data.get("images") or []),
                "url": data.get("url"),
            }
        summaries.append(
            {
                "candidate_key": record.get("candidate_key"),
                "platform": record.get("platform"),
                "listing_id": record.get("listing_id"),
                "params": record.get("params"),
                "ok": envelope is not None and not record.get("error"),
                "detail": detail,
                "error": record.get("error"),
                "raw_file": record.get("raw_file"),
                "credits": int(record.get("credits") or 0),
                "warnings": meta.get("warnings") or [],
                "request_id": meta.get("requestId")
                or ((record.get("error") or {}).get("request_id")),
            }
        )
    return summaries


def _price_probe_summaries(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for record in records:
        envelope = record.get("envelope")
        data = (envelope or {}).get("data")
        meta = (envelope or {}).get("meta") or {}
        summaries.append(
            {
                "candidate_key": record.get("candidate_key"),
                "label": record.get("label"),
                "occupancy": record.get("occupancy"),
                "platform": record.get("platform"),
                "listing_id": record.get("listing_id"),
                "ok": envelope is not None and not record.get("error"),
                "quote": data if isinstance(data, dict) else None,
                "error": record.get("error"),
                "raw_file": record.get("raw_file"),
                "credits": int(record.get("credits") or 0),
                "warnings": meta.get("warnings") or [],
                "request_id": meta.get("requestId")
                or ((record.get("error") or {}).get("request_id")),
            }
        )
    return summaries


def assemble_summary(
    *,
    config: dict[str, Any],
    run: dict[str, Any],
    account: dict[str, Any],
    searches: list[dict[str, Any]],
    listing_probes: list[dict[str, Any]],
    price_probes: list[dict[str, Any]],
    budget_skips: list[str],
) -> dict[str, Any]:
    group_total = int(config["adults"]) + int(config["children"])
    properties = analysis.collect_properties(
        searches,
        group_total=group_total,
        center=config.get("center"),
        radius_km=float(config["radius_km"]),
    )
    clusters, _ = analysis.cluster_properties(properties, radius_m=200.0)
    price_checks = analysis.build_price_checks(
        properties,
        price_probes,
        group_total=group_total,
        requested_currency=config["currency"],
    )
    search_summaries = _search_summaries(searches)
    listing_summaries = _listing_summaries(listing_probes)
    price_summaries = _price_probe_summaries(price_probes)
    credits = analysis.build_credit_summary(
        searches=search_summaries,
        listing_probes=listing_summaries,
        price_checks=price_checks,
        config=config,
    )
    answers = analysis.build_answers(
        config=config,
        properties=properties,
        clusters=clusters,
        price_checks=price_checks,
        credits=credits,
        searches=search_summaries,
    )
    return {
        "run": run,
        "config": config,
        "account": account,
        "searches": search_summaries,
        "properties": properties,
        "clusters": clusters,
        "listing_probes": listing_summaries,
        "price_probes": price_summaries,
        "price_checks": price_checks,
        "credits": credits,
        "answers": answers,
        "data_quality": answers.get("data_quality") or {},
        "budget_skips": budget_skips,
    }


def _account_dict(result) -> dict[str, Any]:
    data = result.data if result and result.ok else {}
    credits = (data or {}).get("credits") or {}
    key_info = (data or {}).get("key") or {}
    plan = (data or {}).get("plan") or {}
    rate_limit = (data or {}).get("rateLimit") or {}
    key_env = key_info.get("env")
    return {
        "plan": plan,
        "key_env": key_env,
        "is_sandbox": key_env == "sandbox",
        "available_before": credits.get("available"),
        "available_after": None,
        "held": credits.get("held"),
        "rate_limit": rate_limit.get("requestsPerMinute"),
    }


def _write_analysis_inputs(
    run_dir: Path,
    *,
    config: dict[str, Any],
    run: dict[str, Any],
    account: dict[str, Any],
    searches: list[dict[str, Any]],
    listing_probes: list[dict[str, Any]],
    price_probes: list[dict[str, Any]],
    budget_skips: list[str],
) -> None:
    payload = {
        "version": 1,
        "config": config,
        "run": run,
        "account": account,
        "budget_skips": budget_skips,
        "searches": [
            {
                "spec": record.get("spec"),
                "raw_file": record.get("raw_file"),
                "error": record.get("error"),
            }
            for record in searches
        ],
        "listing_probes": [
            {
                "candidate_key": record.get("candidate_key"),
                "platform": record.get("platform"),
                "listing_id": record.get("listing_id"),
                "params": record.get("params"),
                "raw_file": record.get("raw_file"),
                "error": record.get("error"),
            }
            for record in listing_probes
        ],
        "price_probes": [
            {
                "candidate_key": record.get("candidate_key"),
                "label": record.get("label"),
                "occupancy": record.get("occupancy"),
                "platform": record.get("platform"),
                "listing_id": record.get("listing_id"),
                "params": record.get("params"),
                "raw_file": record.get("raw_file"),
                "error": record.get("error"),
            }
            for record in price_probes
        ],
    }
    (run_dir / "analysis_inputs.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_outputs(run_dir: Path, summary: dict[str, Any]) -> None:
    report.write_summary_json(summary, run_dir / "summary.json")
    (run_dir / "report.md").write_text(report.build_markdown(summary), encoding="utf-8")
    report.write_candidates_csv(summary, run_dir / "candidates.csv")


def _load_payload(run_dir: Path, raw_file: str | None) -> dict[str, Any] | None:
    if not raw_file:
        return None
    path = run_dir / raw_file
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _hydrate_records(
    run_dir: Path,
    entries: list[dict[str, Any]],
    *,
    kind: str,
) -> list[dict[str, Any]]:
    records = []
    for entry in entries:
        payload = _load_payload(run_dir, entry.get("raw_file"))
        envelope = None
        payload_error = None
        if payload:
            if isinstance(payload.get("error"), dict):
                payload_error = payload.get("error")
            payload_data = payload.get("data")
            if isinstance(payload_data, dict) and payload_data.get("status") == "failed":
                payload_error = payload_data.get("error") or payload_error
            if (
                payload_error is None
                and "data" in payload
                and "meta" in payload
                and "_probe_error" not in payload
            ):
                envelope = payload
        error = entry.get("error") or payload_error
        meta = (envelope or {}).get("meta") or {}
        record = dict(entry)
        record["envelope"] = envelope
        record["error"] = error
        record["credits"] = int(meta.get("creditsCharged") or 0)
        record["duration_s"] = 0.0
        record["job"] = None
        if kind == "search":
            record.setdefault("spec", None)
        records.append(record)
    return records


def reanalyze(run_dir: Path) -> dict[str, Any]:
    inputs_path = run_dir / "analysis_inputs.json"
    if not inputs_path.exists():
        raise ValueError(f"Chybí {inputs_path}")
    inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
    run = dict(inputs.get("run") or {})
    run["run_dir"] = str(run_dir)
    searches = _hydrate_records(run_dir, inputs.get("searches") or [], kind="search")
    listing_probes = _hydrate_records(
        run_dir, inputs.get("listing_probes") or [], kind="listing"
    )
    price_probes = _hydrate_records(
        run_dir, inputs.get("price_probes") or [], kind="price"
    )
    summary = assemble_summary(
        config=inputs["config"],
        run=run,
        account=inputs.get("account") or {},
        searches=searches,
        listing_probes=listing_probes,
        price_probes=price_probes,
        budget_skips=inputs.get("budget_skips") or [],
    )
    write_outputs(run_dir, summary)
    return summary


def run_probe(
    config: dict[str, Any],
    client: StayingClient,
    store: RawStore,
) -> dict[str, Any]:
    started_at = now_iso()
    started_monotonic = time.monotonic()

    account_result = client.account()
    account_before = _account_dict(account_result)
    if account_before.get("is_sandbox") and not config["allow_sandbox"]:
        raise RuntimeError(
            "Klíč je sandboxový (stay_test_). Sandbox vrací fixtures, ne reálná data. "
            "Pro reálné ověření použij live klíč (stay_live_) nebo přidej --allow-sandbox."
        )
    if config.get("min_interval") is None and account_before.get("rate_limit"):
        client.min_interval = 60.0 / float(account_before["rate_limit"])

    available = account_before.get("available_before")
    budget_limit = int(config["max_credits"])
    if available is not None:
        budget_limit = min(budget_limit, int(available))
    if budget_limit <= 0:
        raise RuntimeError("Na účtu nejsou dostupné kredity")
    budget = Budget(limit=budget_limit)

    log(
        f"Účet: {account_before.get('key_env')}, plán {((account_before.get('plan') or {}).get('code'))}, "
        f"dostupné {available}, rozpočet {budget.limit} kr., "
        f"rate limit {account_before.get('rate_limit')}/min"
    )

    search_records = _execute_searches(client, config, budget)
    fatal = any(record.get("fatal") or record.get("abort") for record in search_records)
    listing_records: list[dict[str, Any]] = []
    price_records: list[dict[str, Any]] = []
    if fatal:
        reason = "detaily přeskočeny po chybě hledání"
        budget.skips.append(reason)
        log(reason)
    else:
        prelim = analysis.collect_properties(
            search_records,
            group_total=int(config["adults"]) + int(config["children"]),
            center=config.get("center"),
            radius_km=float(config["radius_km"]),
        )
        analysis.cluster_properties(prelim, radius_m=200.0)
        candidates = _select_candidates(prelim, config)
        log(f"Kandidáti na detail: {len(candidates)}")
        listing_records, price_records = _execute_details(
            client, config, budget, candidates
        )

    account_after_result = None
    try:
        account_after_result = client.account()
    except StayingAPIError as exc:
        log(f"Účet po běhu nelze načíst: {exc}")

    available_after = None
    account = dict(account_before)
    if account_after_result and account_after_result.ok:
        after_data = _account_dict(account_after_result)
        account["available_after"] = after_data.get("available_before")
        account["plan_after"] = after_data.get("plan")
        account["held_after"] = after_data.get("held")

    run = {
        "started_at": started_at,
        "finished_at": now_iso(),
        "run_dir": str(store.run_dir),
        "duration_s": round(time.monotonic() - started_monotonic, 1),
    }
    summary = assemble_summary(
        config=config,
        run=run,
        account=account,
        searches=search_records,
        listing_probes=listing_records,
        price_probes=price_records,
        budget_skips=budget.skips,
    )
    _write_analysis_inputs(
        store.run_dir,
        config=config,
        run=run,
        account=account,
        searches=search_records,
        listing_probes=listing_records,
        price_probes=price_records,
        budget_skips=budget.skips,
    )
    write_outputs(store.run_dir, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ověří StayingAPI na malém vzorku pro jednu lokalitu a termín."
    )
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--check-in", default=DEFAULT_CHECK_IN)
    parser.add_argument("--nights", type=int, default=DEFAULT_NIGHTS)
    parser.add_argument("--adults", type=int, default=DEFAULT_ADULTS)
    parser.add_argument(
        "--children",
        "--child-ages",
        dest="children",
        default=DEFAULT_CHILDREN_AGES,
        help="Věky dětí oddělené čárkou, např. 6,9,12",
    )
    parser.add_argument("--platforms", default=DEFAULT_PLATFORMS)
    parser.add_argument("--currency", default=DEFAULT_CURRENCY)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--rooms",
        type=int,
        default=1,
        help="Parametr rooms pro search; u velké skupiny zkuste 2–4",
    )
    parser.add_argument("--max-credits", type=int, default=DEFAULT_MAX_CREDITS)
    parser.add_argument(
        "--detail-candidates", type=int, default=DEFAULT_DETAIL_CANDIDATES
    )
    parser.add_argument("--split-probes", type=int, default=DEFAULT_SPLIT_PROBES)
    parser.add_argument("--radius-km", type=float, default=DEFAULT_RADIUS_KM)
    parser.add_argument("--center", default=None, help="lat,lng; jinak Schladming")
    parser.add_argument(
        "--sub-occupancies",
        default=None,
        help="Vlastní menší obsazení, např. '8A+2C,6A+1C,4A,2A'",
    )
    parser.add_argument(
        "--max-sub-searches",
        type=int,
        default=5,
        help="Kolik menších obsazení automaticky vygenerovat",
    )
    parser.add_argument("--min-interval", type=float, default=None)
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="Maximální čekání na jednu asynchronní úlohu v sekundách",
    )
    parser.add_argument("--out", default="data/runs")
    parser.add_argument("--allow-sandbox", action="store_true")
    parser.add_argument(
        "--continue-on-upstream-error",
        action="store_true",
        help="Nezastavovat po výpadku upstreamu; zkusit i další obsazení.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reanalyze", default=None, help="Znovu analyzovat existující run")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    load_dotenv()

    if args.reanalyze:
        run_dir = Path(args.reanalyze)
        try:
            summary = reanalyze(run_dir)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"Chyba: {exc}", file=sys.stderr)
            return 2
        print(f"Přepsáno: {run_dir / 'report.md'}")
        print(f"Kredity v runu: {summary['credits']['total']}")
        return 0

    try:
        config = build_config(args)
    except (ValueError, TypeError) as exc:
        print(f"Chyba v parametrech: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print_plan(config)
        return 0

    api_key = os.environ.get("STAYINGAPI_KEY", "").strip()
    if not api_key:
        print(
            "Chybí STAYINGAPI_KEY.\n"
            "Vlož ho do .env (viz .env.example) nebo ho exportuj v prostředí.\n"
            "Pro reálné ověření použij live klíč stay_live_...; sandbox vyžaduje --allow-sandbox.\n"
            "Dry-run: python probe_stayingapi.py --dry-run",
            file=sys.stderr,
        )
        return 2

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    location_slug = re.sub(r"[^a-z0-9]+", "-", config["location"].lower()).strip("-")[:30]
    run_dir = Path(args.out) / f"{run_id}-{location_slug or 'run'}"
    suffix = 2
    while run_dir.exists():
        run_dir = Path(args.out) / f"{run_id}-{location_slug or 'run'}-{suffix}"
        suffix += 1
    store = RawStore(run_dir)
    client = StayingClient(
        api_key,
        base_url=os.environ.get("STAYINGAPI_BASE_URL", "https://api.stayingapi.com"),
        store=store,
        timeout=90.0,
        max_wait=args.timeout,
        min_interval=args.min_interval,
        logger=log if args.verbose else None,
    )
    try:
        summary = run_probe(config, client, store)
    except StayingAPIError as exc:
        print(f"API chyba: {exc}", file=sys.stderr)
        if exc.request_id:
            print(f"requestId: {exc.request_id}", file=sys.stderr)
        return 4
    except RuntimeError as exc:
        print(f"Chyba: {exc}", file=sys.stderr)
        return 3
    finally:
        client.close()

    print(f"Hotovo: {run_dir}")
    print(f"  report:  {run_dir / 'report.md'}")
    print(f"  summary: {run_dir / 'summary.json'}")
    print(f"  tabulka: {run_dir / 'candidates.csv'}")
    print(f"  raw:     {run_dir / 'raw'}")
    print(f"  kredity: {summary['credits']['total']}")
    for key in ("q1_scope", "q2_fields", "q3_price_by_occupancy", "q4_units_in_same_house", "q5_credit_cost"):
        answer = summary["answers"].get(key) or {}
        print(f"  {key}: {answer.get('status')}")
    return 0
