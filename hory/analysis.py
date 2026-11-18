from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any

WHOLE_WORDS = {
    "house",
    "chalet",
    "villa",
    "cottage",
    "ferienhaus",
    "haus",
    "huette",
    "hutte",
    "landhaus",
    "bauernhaus",
    "almhuette",
    "alm",
    "dom",
    "chalupa",
    "casa",
    "vila",
    "entire",
    "whole",
    "cely",
    "komplett",
}

UNIT_WORDS = {
    "apartment",
    "apartments",
    "apartman",
    "apartmany",
    "wohnung",
    "wohnungen",
    "ferienwohnung",
    "ferienwohnungen",
    "studio",
    "room",
    "rooms",
    "zimmer",
    "suite",
    "suites",
    "unit",
    "loft",
}

PLURAL_BUILDING_WORDS = {
    "apartments",
    "apartmany",
    "wohnungen",
    "ferienwohnungen",
    "rooms",
    "zimmer",
    "suites",
    "units",
}

GENERIC_NAME_WORDS = {
    "apartment",
    "apartments",
    "apartman",
    "apartmany",
    "wohnung",
    "wohnungen",
    "ferienwohnung",
    "ferienwohnungen",
    "house",
    "haus",
    "chalet",
    "villa",
    "cottage",
    "ferienhaus",
    "room",
    "rooms",
    "zimmer",
    "studio",
    "suite",
    "suites",
    "unit",
    "the",
    "at",
    "in",
    "by",
    "and",
    "und",
    "mit",
    "am",
    "an",
    "der",
    "die",
    "das",
    "les",
    "la",
    "le",
    "el",
}


def strip_diacritics(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def normalize_text(value: str) -> str:
    value = strip_diacritics(value or "").lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def name_tokens(value: str) -> list[str]:
    return [token for token in normalize_text(value).split() if token]


def normalized_name(value: str, *, drop_numbers: bool = False) -> str:
    tokens = []
    for token in name_tokens(value):
        if token in GENERIC_NAME_WORDS:
            continue
        if drop_numbers and token.isdigit():
            continue
        tokens.append(token)
    return " ".join(tokens)


def name_similarity(left: str, right: str) -> float:
    a = normalized_name(left)
    b = normalized_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    return SequenceMatcher(None, a, b).ratio()


def distance_km(lat1: float | None, lng1: float | None, lat2: float | None, lng2: float | None) -> float | None:
    if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
        return None
    radius = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * radius * math.asin(math.sqrt(a))


def property_key(prop: dict[str, Any]) -> str:
    platform = str(prop.get("platform") or "").strip()
    listing_id = str(prop.get("platformListingId") or "").strip()
    if platform and listing_id:
        return f"{platform}:{listing_id}"
    composite = str(prop.get("id") or "").strip()
    if composite:
        return composite
    location = prop.get("location") or {}
    name = normalize_text(str(prop.get("name") or "unknown"))
    return f"{platform}:{name}:{location.get('lat')}:{location.get('lng')}"


def classify_scope(prop: dict[str, Any], group_total: int) -> dict[str, Any]:
    name = str(prop.get("name") or "")
    normalized = normalize_text(name)
    tokens = set(name_tokens(name))
    property_type = str(prop.get("propertyType") or "").lower() or None
    max_occupancy = prop.get("maxOccupancy")
    reasons: list[str] = []
    flags: list[str] = []

    has_whole = bool(tokens & WHOLE_WORDS)
    has_unit = bool(tokens & UNIT_WORDS)
    plural_building = bool(tokens & PLURAL_BUILDING_WORDS)
    has_unit_number = bool(
        re.search(
            r"\b(?:no|nr|unit|apartment|apt|top|eg|og|ug|zi|zimmer)?\s*\d{1,3}\b",
            normalized,
        )
    )

    scope = "unknown"
    confidence = "low"

    if property_type in {"house", "villa", "cottage"}:
        scope = "whole_property"
        confidence = "medium"
        reasons.append(f"propertyType={property_type}")
    elif property_type == "hotel":
        scope = "single_unit"
        confidence = "high"
        reasons.append("propertyType=hotel (pokoj)")
    elif property_type == "apartment":
        if plural_building:
            scope = "unknown"
            confidence = "low"
            reasons.append("název v plurálu (budova s více jednotkami)")
        elif has_unit_number:
            scope = "single_unit"
            confidence = "medium"
            reasons.append("název obsahuje číslo jednotky")
        else:
            scope = "single_unit"
            confidence = "low"
            reasons.append("propertyType=apartment")
    else:
        reasons.append("propertyType chybí nebo je jiný")

    if has_whole and not has_unit:
        scope = "whole_property"
        confidence = "high" if tokens & {"entire", "whole", "cely", "komplett"} else "medium"
        reasons.append("název obsahuje signál celého objektu")
    elif has_whole and has_unit:
        reasons.append("název obsahuje signály celého objektu i jednotky")

    if plural_building and not has_unit_number:
        flags.append("building_name_without_unit_number")

    if max_occupancy is None:
        flags.append("capacity_unknown")
        reasons.append("maxOccupancy chybí")
    else:
        try:
            occupancy_value = int(max_occupancy)
        except (TypeError, ValueError):
            occupancy_value = None
        if occupancy_value is not None and occupancy_value < group_total:
            flags.append("capacity_below_group")
            reasons.append(f"maxOccupancy={occupancy_value} < skupina {group_total}")

    return {
        "scope": scope,
        "confidence": confidence,
        "reasons": reasons,
        "flags": flags,
    }


def collect_properties(
    searches: list[dict[str, Any]],
    *,
    group_total: int,
    center: dict[str, float] | None,
    radius_km: float,
) -> list[dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}

    for search in searches:
        envelope = search.get("envelope")
        if not envelope:
            continue
        spec = search.get("spec") or {}
        data = envelope.get("data")
        if not isinstance(data, list):
            continue
        for prop in data:
            if not isinstance(prop, dict):
                continue
            key = property_key(prop)
            entry = registry.get(key)
            if entry is None:
                location = prop.get("location") or {}
                entry = {
                    "key": key,
                    "id": prop.get("id"),
                    "platform": prop.get("platform"),
                    "platform_listing_id": prop.get("platformListingId"),
                    "name": prop.get("name"),
                    "property_type": prop.get("propertyType"),
                    "star_rating": prop.get("starRating"),
                    "guest_rating": prop.get("guestRating"),
                    "rating_scale": prop.get("ratingScale"),
                    "review_count": prop.get("reviewCount"),
                    "max_occupancy": prop.get("maxOccupancy"),
                    "bedrooms": prop.get("bedrooms"),
                    "bathrooms": prop.get("bathrooms"),
                    "amenities": prop.get("amenities") or [],
                    "images": prop.get("images") or [],
                    "host": prop.get("host"),
                    "url": prop.get("url"),
                    "location": location,
                    "observations": [],
                    "source_searches": [],
                }
                registry[key] = entry
            search_key = spec.get("key") or "unknown"
            if search_key in entry["source_searches"]:
                continue
            entry["source_searches"].append(search_key)
            entry["observations"].append(
                {
                    "search_key": search_key,
                    "search_label": spec.get("label") or search_key,
                    "occupancy": {
                        "adults": spec.get("adults"),
                        "children": spec.get("children"),
                        "child_ages": spec.get("child_ages") or [],
                    },
                    "price": prop.get("price"),
                    "max_occupancy": prop.get("maxOccupancy"),
                    "property_type": prop.get("propertyType"),
                    "name": prop.get("name"),
                    "url": prop.get("url"),
                    "location": prop.get("location"),
                }
            )

    properties: list[dict[str, Any]] = []
    for entry in registry.values():
        observations = entry["observations"]
        primary = next(
            (obs for obs in observations if obs["search_key"] == "whole"),
            None,
        )
        if primary is None and observations:
            primary = max(
                observations,
                key=lambda obs: (obs["occupancy"].get("adults") or 0)
                + (obs["occupancy"].get("children") or 0),
            )
        if primary is None:
            continue

        entry["primary_search"] = primary["search_key"]
        entry["primary_occupancy"] = primary["occupancy"]
        entry["search_price"] = primary.get("price")
        entry["search_price_total"] = (primary.get("price") or {}).get("totalPrice")
        entry["search_price_currency"] = (primary.get("price") or {}).get("currency")
        entry["has_whole_observation"] = any(
            obs["search_key"] == "whole" for obs in observations
        )

        location = entry.get("location") or {}
        distance = distance_km(
            center.get("lat") if center else None,
            center.get("lng") if center else None,
            location.get("lat"),
            location.get("lng"),
        )
        entry["distance_km"] = round(distance, 2) if distance is not None else None
        entry["in_radius"] = distance is None or distance <= radius_km
        entry["location_unknown"] = location.get("lat") is None or location.get("lng") is None

        scope = classify_scope(
            {
                "name": entry.get("name"),
                "propertyType": entry.get("property_type"),
                "maxOccupancy": entry.get("max_occupancy"),
            },
            group_total,
        )
        entry["scope"] = scope["scope"]
        entry["scope_confidence"] = scope["confidence"]
        entry["scope_reasons"] = scope["reasons"]
        entry["flags"] = list(scope["flags"])

        if entry["location_unknown"]:
            entry["flags"].append("location_unknown")
        if entry.get("search_price_total") is None:
            entry["flags"].append("search_price_missing")
        if "capacity_below_group" in entry["flags"] and entry.get("search_price_total") is not None:
            entry["flags"].append("search_price_may_be_multi_room")
            entry["scope_reasons"].append(
                "search cena existuje i při kapacitě nižší než skupina"
            )
        try:
            capacity_value = int(entry["max_occupancy"]) if entry["max_occupancy"] is not None else None
        except (TypeError, ValueError):
            capacity_value = None
        entry["capacity_ok"] = capacity_value is not None and capacity_value >= group_total
        entry["capacity_known"] = capacity_value is not None
        properties.append(entry)

    properties.sort(
        key=lambda item: (
            0 if item.get("in_radius") else 1,
            item.get("distance_km") if item.get("distance_km") is not None else 9999,
            item.get("search_price_total") if item.get("search_price_total") is not None else 1e12,
            str(item.get("name") or ""),
        )
    )
    return properties


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def cluster_properties(
    properties: list[dict[str, Any]],
    *,
    radius_m: float = 200.0,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    usable = [prop for prop in properties if prop.get("in_radius", True)]
    union = _UnionFind()
    for prop in usable:
        union.find(prop["key"])

    for index, left in enumerate(usable):
        for right in usable[index + 1 :]:
            left_location = left.get("location") or {}
            right_location = right.get("location") or {}
            distance = distance_km(
                left_location.get("lat"),
                left_location.get("lng"),
                right_location.get("lat"),
                right_location.get("lng"),
            )
            similarity = name_similarity(left.get("name") or "", right.get("name") or "")
            compact_left = normalized_name(left.get("name") or "", drop_numbers=True)
            compact_right = normalized_name(right.get("name") or "", drop_numbers=True)
            same_compact = bool(compact_left) and compact_left == compact_right

            close_enough = distance is not None and distance <= radius_m / 1000.0
            if close_enough and (similarity >= 0.75 or same_compact):
                union.union(left["key"], right["key"])
                continue
            if distance is None and same_compact and len(compact_left) >= 5:
                union.union(left["key"], right["key"])
                continue
            if distance is not None and distance <= 0.5 and same_compact:
                union.union(left["key"], right["key"])

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cluster_by_key: dict[str, str] = {}
    for prop in usable:
        root = union.find(prop["key"])
        grouped[root].append(prop)
        cluster_by_key[prop["key"]] = root

    clusters: list[dict[str, Any]] = []
    for index, (root, members) in enumerate(
        sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])),
        start=1,
    ):
        cluster_id = f"c{index}"
        for member in members:
            member["cluster_id"] = cluster_id
            cluster_by_key[member["key"]] = cluster_id

        pair_distances: list[float] = []
        cross_platform_pairs: list[dict[str, Any]] = []
        same_platform_pairs: list[dict[str, Any]] = []
        for left_index, left in enumerate(members):
            for right in members[left_index + 1 :]:
                left_location = left.get("location") or {}
                right_location = right.get("location") or {}
                distance = distance_km(
                    left_location.get("lat"),
                    left_location.get("lng"),
                    right_location.get("lat"),
                    right_location.get("lng"),
                )
                if distance is not None:
                    pair_distances.append(distance)
                pair = {
                    "left": left["key"],
                    "right": right["key"],
                    "distance_m": round(distance * 1000) if distance is not None else None,
                    "name_similarity": round(
                        name_similarity(left.get("name") or "", right.get("name") or ""),
                        3,
                    ),
                }
                if left.get("platform") != right.get("platform"):
                    cross_platform_pairs.append(pair)
                else:
                    same_platform_pairs.append(pair)

        cross_duplicate = any(
            (pair["distance_m"] is None or pair["distance_m"] <= 120)
            and pair["name_similarity"] >= 0.85
            for pair in cross_platform_pairs
        )
        same_platform_units = any(
            pair["name_similarity"] >= 0.75
            and (pair["distance_m"] is None or pair["distance_m"] <= radius_m)
            for pair in same_platform_pairs
        )

        if cross_duplicate and same_platform_units:
            interpretation = "smíšené: pravděpodobná duplicita i možné jednotky"
        elif cross_duplicate:
            interpretation = "pravděpodobně stejná jednotka na více platformách"
        elif same_platform_units:
            interpretation = "možná více jednotek ve stejném domě (neověřeno)"
        elif len(members) > 1:
            interpretation = "blízké nabídky, vztah neověřen"
        else:
            interpretation = "samostatná nabídka"

        clusters.append(
            {
                "cluster_id": cluster_id,
                "size": len(members),
                "members": [
                    {
                        "key": member["key"],
                        "name": member.get("name"),
                        "platform": member.get("platform"),
                        "platform_listing_id": member.get("platform_listing_id"),
                        "property_type": member.get("property_type"),
                        "max_occupancy": member.get("max_occupancy"),
                        "distance_km": member.get("distance_km"),
                        "url": member.get("url"),
                    }
                    for member in members
                ],
                "platforms": sorted({str(member.get("platform")) for member in members}),
                "span_m": round(max(pair_distances) * 1000) if pair_distances else 0,
                "cross_platform_pairs": cross_platform_pairs,
                "same_platform_pairs": same_platform_pairs,
                "cross_platform_duplicate": cross_duplicate,
                "same_platform_multiple_units": same_platform_units,
                "suspected_same_house": len(members) > 1,
                "interpretation": interpretation,
            }
        )

    return clusters, cluster_by_key


def price_relation(search_price: Any, quote_price: Any) -> tuple[str, float | None]:
    search_total = (search_price or {}).get("totalPrice")
    quote_total = (quote_price or {}).get("totalPrice")
    if search_total is None and quote_total is None:
        return "missing_both", None
    if quote_total is None:
        return "quote_missing", None
    if search_total is None:
        return "quote_only", None
    try:
        search_value = float(search_total)
        quote_value = float(quote_total)
    except (TypeError, ValueError):
        return "unknown", None
    if search_value <= 0:
        return "unknown", None
    delta = (quote_value - search_value) / search_value
    if delta > 0.10:
        return "quote_higher", delta
    if delta < -0.10:
        return "quote_lower", delta
    return "match", delta


def quote_flags(
    quote: dict[str, Any] | None,
    *,
    requested_currency: str,
    meta_warnings: list[str] | None = None,
) -> list[str]:
    if not quote:
        return []
    flags: list[str] = []
    currency = quote.get("currency")
    if currency and requested_currency and currency.upper() != requested_currency.upper():
        flags.append("currency_passthrough")
    basis = quote.get("priceBasis")
    if basis == "nightly_rate_x_nights":
        flags.append("price_is_estimate")
    elif basis == "displayed_stay_price":
        flags.append("taxes_may_be_extra")
    elif basis == "quoted_total":
        pass
    else:
        flags.append("price_basis_unknown")
    fees = quote.get("fees") or {}
    if all(fees.get(key) is None for key in ("cleaning", "service", "taxes")):
        flags.append("fees_not_itemized")
    for warning in meta_warnings or []:
        if warning not in flags:
            flags.append(str(warning))
    return flags


def build_price_checks(
    properties: list[dict[str, Any]],
    price_probes: list[dict[str, Any]],
    *,
    group_total: int,
    requested_currency: str,
) -> list[dict[str, Any]]:
    by_key = {prop["key"]: prop for prop in properties}
    checks: list[dict[str, Any]] = []

    for probe in price_probes:
        candidate_key = probe.get("candidate_key")
        prop = by_key.get(candidate_key)
        if not prop:
            continue
        envelope = probe.get("envelope")
        error = probe.get("error")
        quote = None
        meta_warnings: list[str] = []
        credits = 0
        if envelope:
            quote = envelope.get("data") if isinstance(envelope.get("data"), dict) else None
            meta = envelope.get("meta") or {}
            credits = int(meta.get("creditsCharged") or 0)
            meta_warnings = list(meta.get("warnings") or [])

        occupancy = probe.get("occupancy") or {}
        search_price = None
        for observation in prop.get("observations") or []:
            obs_occupancy = observation.get("occupancy") or {}
            if (
                obs_occupancy.get("adults") == occupancy.get("adults")
                and obs_occupancy.get("children") == occupancy.get("children")
            ):
                search_price = observation.get("price")
                break

        relation, delta = price_relation(search_price, quote)
        flags = quote_flags(
            quote,
            requested_currency=requested_currency,
            meta_warnings=meta_warnings,
        )
        if error:
            code = (error or {}).get("code")
            if code == "no_availability" and search_price:
                flags.append("search_price_but_single_unit_no_availability")
        if delta is not None:
            flags.append("price_delta_over_10pct" if abs(delta) > 0.10 else "price_delta_within_10pct")

        checks.append(
            {
                "candidate_key": candidate_key,
                "name": prop.get("name"),
                "platform": prop.get("platform"),
                "occupancy_label": probe.get("label"),
                "occupancy": occupancy,
                "search_price": search_price,
                "quote": quote,
                "error": error,
                "relation": relation,
                "delta_pct": round(delta * 100, 1) if delta is not None else None,
                "flags": flags,
                "credits": credits,
                "raw_file": probe.get("raw_file"),
                "meta_warnings": meta_warnings,
            }
        )

    return checks


def _coverage(properties: list[dict[str, Any]], predicate) -> tuple[int, int]:
    total = len(properties)
    present = sum(1 for prop in properties if predicate(prop))
    return present, total


def build_answers(
    *,
    config: dict[str, Any],
    properties: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    price_checks: list[dict[str, Any]],
    credits: dict[str, Any],
    searches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    in_radius = [prop for prop in properties if prop.get("in_radius", True)]
    scope_counts: dict[str, int] = defaultdict(int)
    for prop in in_radius:
        scope_counts[str(prop.get("scope") or "unknown")] += 1

    mismatch = [
        check
        for check in price_checks
        if "search_price_but_single_unit_no_availability" in check.get("flags", [])
    ]
    capacity_below = [
        prop for prop in in_radius if "capacity_below_group" in prop.get("flags", [])
    ]
    multi_room_suspected = [
        prop for prop in in_radius if "search_price_may_be_multi_room" in prop.get("flags", [])
    ]

    if mismatch or capacity_below:
        q1_status = "ČÁSTEČNĚ"
        q1_text = (
            "Část nabídek nevypadá na jednu rezervovatelnou jednotku pro celou skupinu. "
            "API u nich vrátilo search cenu, ale kapacita je nižší než skupina, případně "
            "cenový dotaz pro celou skupinu selhal. To odpovídá dokumentovanému chování "
            "Booking.com, kde search cena může být složena z více pokojů."
        )
    elif in_radius and scope_counts.get("whole_property", 0) == len(in_radius):
        q1_status = "ANO (na vzorku)"
        q1_text = (
            "Všechny nabídky ve vzorku mají typ nebo název celého objektu a kapacitu "
            "pokrývající skupinu. API však explicitně neuvádí, že jde o celý dům; "
            "jde o odhad z propertyType, názvu a kapacity."
        )
    elif in_radius:
        q1_status = "NELZE URČIT"
        q1_text = (
            "API vrací propertyType, název a kapacitu, ale neuvádí explicitně rozsah "
            "nabídky (jednotka vs celý dům). Bez cenového ověření nelze vztah potvrdit."
        )
    else:
        q1_status = "NELZE URČIT"
        q1_text = "Ve vzorku nejsou žádné nabídky v zadaném okruhu."

    capacity_present, capacity_total = _coverage(
        in_radius, lambda prop: prop.get("max_occupancy") is not None
    )
    coords_present, coords_total = _coverage(
        in_radius,
        lambda prop: not prop.get("location_unknown"),
    )
    ids_present, ids_total = _coverage(
        in_radius,
        lambda prop: bool(prop.get("platform_listing_id")),
    )
    type_present, type_total = _coverage(
        in_radius,
        lambda prop: bool(prop.get("property_type")),
    )

    def ratio(present: int, total: int) -> float:
        return (present / total) if total else 0.0

    core_ratios = [
        ratio(capacity_present, capacity_total),
        ratio(coords_present, coords_total),
        ratio(ids_present, ids_total),
        ratio(type_present, type_total),
    ]
    if in_radius and all(value >= 0.99 for value in core_ratios):
        q2_status = "ANO"
    elif in_radius and all(value >= 0.5 for value in core_ratios):
        q2_status = "ČÁSTEČNĚ"
    elif in_radius:
        q2_status = "NE"
    else:
        q2_status = "NELZE URČIT"
    q2_text = (
        f"Kapacita {capacity_present}/{capacity_total}, souřadnice {coords_present}/{coords_total}, "
        f"platformní ID {ids_present}/{ids_total}, propertyType {type_present}/{type_total}. "
        "Počet ložnic a koupelen může být null; API nevrací počet lůžek ani inventář jednotek v domě."
    )

    successful_quotes = [
        check
        for check in price_checks
        if check.get("quote")
        and not check.get("error")
        and (check.get("quote") or {}).get("totalPrice") is not None
    ]
    quotes_with_children = [
        check
        for check in successful_quotes
        if (check.get("occupancy") or {}).get("children", 0) > 0
    ]
    if successful_quotes:
        q3_status = "ANO s výhradami"
        q3_text = (
            f"Cenový endpoint vrátil {len(successful_quotes)} platných nabídek, z toho "
            f"{len(quotes_with_children)} s konkrétními věky dětí. Cena je ale garantovaná "
            "pro jednu rezervovatelnou jednotku; u Booking.com nemusí odpovídat search ceně "
            "složené z více pokojů. U estimate/displayed basis mohou chybět daně či poplatky."
        )
    elif price_checks:
        q3_status = "NE"
        q3_text = (
            "Cenové dotazy byly provedeny, ale nevrátily použitelnou cenu. Je potřeba "
            "zkontrolovat chyby níže (no_availability, identity_mismatch, rate limit)."
        )
    else:
        q3_status = "NELZE URČIT"
        q3_text = "Cenové dotazy nebyly provedeny."

    same_platform_clusters = [
        cluster
        for cluster in clusters
        if cluster.get("size", 0) > 1 and cluster.get("same_platform_multiple_units")
    ]
    cross_duplicate_clusters = [
        cluster
        for cluster in clusters
        if cluster.get("size", 0) > 1 and cluster.get("cross_platform_duplicate")
    ]
    if same_platform_clusters:
        q4_status = "ČÁSTEČNĚ (neověřeno)"
        q4_text = (
            f"Na vzorku je {len(same_platform_clusters)} clusterů, kde stejná platforma "
            "vrací více blízkých nabídek s podobným názvem. To může znamenat více jednotek "
            "ve stejném domě, ale API nevrací inventář jednotek ani jejich vzájemnou "
            "dostupnost. Vztah je nutné potvrdit ručně nebo dalším zdrojem."
        )
    elif cross_duplicate_clusters:
        q4_status = "NE"
        q4_text = (
            "Vidíme pouze pravděpodobné duplicity stejné jednotky na více platformách. "
            "API neumožňuje rozlišit samostatně rezervovatelné jednotky ve stejném domě."
        )
    elif clusters and any(cluster.get("size", 0) > 1 for cluster in clusters):
        q4_status = "NELZE URČIT"
        q4_text = (
            "Několik nabídek je blízko sebe, ale bez inventáře jednotek nelze říct, zda "
            "jde o stejnou jednotku, duplicitu, nebo více jednotek v domě."
        )
    else:
        q4_status = "NE / NELZE URČIT"
        q4_text = (
            "API nevrací seznam jednotek v domě. Ze samotných search výsledků nelze "
            "spolehlivě určit, které jednotky jsou samostatně rezervovatelné."
        )

    q5_status = "ANO (změřeno)"
    q5_text = (
        f"Celkem {credits.get('total', 0)} kreditů: hledání {credits.get('search', 0)}, "
        f"detaily {credits.get('listing', 0)}, ceny {credits.get('price', 0)}. "
        f"Jeden search dotaz má worst-case {credits.get('search_worst_case', 0)} kreditů; "
        f"celý probe ({credits.get('search_count', 0)} dotazů + ověření) má worst-case "
        f"{credits.get('probe_worst_case', 0)} kreditů. Skutečná cena závisí na počtu "
        "vrácených výsledků; cache hit se stále účtuje."
    )

    search_list = searches or []
    successful_searches = [search for search in search_list if search.get("ok")]
    failed_searches = [search for search in search_list if not search.get("ok")]
    all_failed = bool(search_list) and not successful_searches
    partial = bool(successful_searches) and bool(failed_searches)
    errors = []
    for search in failed_searches:
        error = search.get("error") or {}
        errors.append(
            {
                "key": search.get("key"),
                "label": search.get("label"),
                "type": error.get("type"),
                "code": error.get("code"),
                "message": error.get("message"),
                "request_id": error.get("request_id")
                or search.get("request_id"),
                "raw_file": search.get("raw_file"),
            }
        )
    data_quality = {
        "successful_searches": len(successful_searches),
        "failed_searches": len(failed_searches),
        "all_failed": all_failed,
        "partial": partial,
        "errors": errors,
    }

    if all_failed:
        q1_status = q2_status = q3_status = q4_status = "NELZE URČIT (hledání selhalo)"
        failure_text = (
            f"Žádné z {len(search_list)} search volání neproběhlo úspěšně. "
            "Tento vzorek neříká nic o nabídce v lokalitě; nejde o potvrzení, že by "
            "ubytování neexistovalo. Podívejte se na chyby a requestId níže."
        )
        q1_text = q2_text = q3_text = q4_text = failure_text
        q5_status = "NELZE (hledání selhalo)"
        q5_text = (
            f"Všech {len(search_list)} search volání selhalo, proto se neúčtovaly žádné "
            f"kredity (celkem {credits.get('total', 0)}). Worst-case jednoho dotazu je "
            f"{credits.get('search_worst_case', 0)} kreditů; skutečnou cenu nelze změřit, "
            "dokud API nevrátí data."
        )
    elif partial:
        prefix = (
            f"Pozor: {len(failed_searches)} z {len(search_list)} search dotazů selhalo; "
            "výsledky jsou neúplné. "
        )
        q1_text = prefix + q1_text
        q2_text = prefix + q2_text
        q3_text = prefix + q3_text
        q4_text = prefix + q4_text
        q5_status = "ČÁSTEČNĚ"
        q5_text = prefix + q5_text

    return {
        "data_quality": data_quality,
        "q1_scope": {
            "status": q1_status,
            "text": q1_text,
            "evidence": {
                "scope_counts": dict(scope_counts),
                "capacity_below_group": len(capacity_below),
                "multi_room_suspected": len(multi_room_suspected),
                "search_price_but_no_single_unit": len(mismatch),
            },
        },
        "q2_fields": {
            "status": q2_status,
            "text": q2_text,
            "evidence": {
                "max_occupancy": [capacity_present, capacity_total],
                "coordinates": [coords_present, coords_total],
                "platform_ids": [ids_present, ids_total],
                "property_type": [type_present, type_total],
            },
        },
        "q3_price_by_occupancy": {
            "status": q3_status,
            "text": q3_text,
            "evidence": {
                "successful_quotes": len(successful_quotes),
                "quotes_with_children": len(quotes_with_children),
                "price_probes": len(price_checks),
            },
        },
        "q4_units_in_same_house": {
            "status": q4_status,
            "text": q4_text,
            "evidence": {
                "same_platform_clusters": len(same_platform_clusters),
                "cross_platform_duplicate_clusters": len(cross_duplicate_clusters),
                "clusters_total": len(clusters),
            },
        },
        "q5_credit_cost": {
            "status": q5_status,
            "text": q5_text,
            "evidence": credits,
        },
    }


def search_worst_case(platforms: list[str], limit: int) -> int:
    per_result = {"airbnb": 2, "booking": 1, "vrbo": 1}
    total = 0
    for platform in platforms:
        if platform == "google":
            total += 15 * math.ceil(limit / 20)
        else:
            total += max(5, per_result.get(platform, 1) * limit)
    return total


def listing_cost(platform: str) -> int:
    return 15 if platform == "vrbo" else 3


def build_credit_summary(
    *,
    searches: list[dict[str, Any]],
    listing_probes: list[dict[str, Any]],
    price_checks: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    search_credits = sum(int(search.get("credits") or 0) for search in searches)
    listing_credits = sum(int(probe.get("credits") or 0) for probe in listing_probes)
    price_credits = sum(int(check.get("credits") or 0) for check in price_checks)
    per_search = [
        {
            "key": search.get("key"),
            "label": search.get("label"),
            "credits": int(search.get("credits") or 0),
            "count": search.get("count", 0),
        }
        for search in searches
    ]
    return {
        "search": search_credits,
        "listing": listing_credits,
        "price": price_credits,
        "total": search_credits + listing_credits + price_credits,
        "per_search": per_search,
        "search_worst_case": search_worst_case(
            list(config.get("platforms") or []),
            int(config.get("limit") or 10),
        ),
        "search_count": len(searches),
        "detail_reserve": int(config.get("detail_reserve") or 0),
        "probe_worst_case": search_worst_case(
            list(config.get("platforms") or []),
            int(config.get("limit") or 10),
        )
        * len(searches)
        + int(config.get("detail_reserve") or 0),
    }
