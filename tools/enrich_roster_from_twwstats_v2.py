#!/usr/bin/env python3
"""
Enrich a compact Total War: Warhammer faction roster from TWWStats GraphQL.

V2 fix: prefers the concrete tww_version from the raw JSON input. The TWWStats
broker can answer generic tww_version probes but faction lookups need the exact
numeric version, for example 994043630235584661.

Typical local test:
  python tools/enrich_roster_from_twwstats_v2.py \
    --input norsca_roster_raw.json \
    --faction norsca \
    --faction-value wh_dlc08_nor_norsca \
    --out norsca_roster.enriched.json \
    --raw-out norsca_roster.enriched_raw.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

UA = "Mozilla/5.0 TWWRosterEnricherV2/0.1"
SSL_CONTEXT = ssl._create_unverified_context()
ENDPOINTS = (
    "https://broker.twwstats.com/graphql",
    "https://twwstats.com/graphql",
    "https://www.twwstats.com/graphql",
    "https://twwstats.com/api/graphql",
    "https://www.twwstats.com/api/graphql",
)

FACTION_GUESSES: Dict[str, List[str]] = {
    "norsca": [
        "wh_dlc08_nor_norsca",
        "wh_dlc08_sc_nor_norsca",
        "wh_main_nor_norsca",
        "wh_main_sc_nor_norsca",
        "norsca",
        "nor",
    ],
    "khorne": [
        "wh3_main_kho_khorne",
        "wh3_main_sc_kho_khorne",
        "khorne",
        "kho",
    ],
    "skaven": ["wh2_main_skv_skaven", "wh2_main_sc_skv_skaven", "skaven", "skv"],
}

TYPE_REF = """
fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType {
        kind
        name
        ofType {
          kind
          name
        }
      }
    }
  }
}
"""

TYPE_QUERY = TYPE_REF + """
query TypeInfo($name: String!) {
  __type(name: $name) {
    name
    kind
    fields {
      name
      args {
        name
        defaultValue
        type { ...TypeRef }
      }
      type { ...TypeRef }
    }
    enumValues { name }
  }
}
"""

ROOT_QUERY = "query RootInfo { __schema { queryType { name } } }"

STAT_CANDIDATES: Dict[str, Sequence[str]] = {
    "armour": ("stat_armour", "armour", "armor", "armour_value", "armor_value"),
    "leadership": ("stat_leadership", "leadership", "morale", "stat_morale"),
    "speed": ("stat_speed", "speed", "run_speed"),
    "melee_attack": ("stat_melee_attack", "melee_attack", "meleeattack", "melee_attack_value"),
    "melee_defence": ("stat_melee_defence", "stat_melee_defense", "melee_defence", "melee_defense", "meleedefence", "melee_defence_value"),
    "weapon_strength": ("stat_weapon_strength", "weapon_strength", "weaponstrength", "melee_weapon_strength", "melee_damage", "weapon_damage", "damage"),
    "charge_bonus": ("stat_charge_bonus", "charge_bonus", "chargebonus"),
    "ammo": ("stat_ammo", "ammo", "ammunition"),
    "range": ("stat_range", "range", "missile_range", "maximum_range"),
    "missile_strength": ("stat_missile_strength", "missile_strength", "missilestrength", "projectile_damage", "missile_damage"),
    "health": ("stat_health", "health", "hit_points", "hp"),
    "entities": ("num_men", "entities", "entity_count", "soldiers"),
    "mass": ("mass", "entity_mass"),
    "bonus_vs_large": ("bonus_vs_large", "anti_large", "antilarge"),
    "bonus_vs_infantry": ("bonus_vs_infantry", "anti_infantry", "antiinfantry"),
}

SUMMARY_ORDER: Sequence[Tuple[str, str]] = (
    ("armour", "Arm"),
    ("leadership", "Ld"),
    ("speed", "Spd"),
    ("melee_attack", "MA"),
    ("melee_defence", "MD"),
    ("weapon_strength", "WS"),
    ("charge_bonus", "CB"),
    ("ammo", "Ammo"),
    ("range", "Rng"),
    ("missile_strength", "MS"),
)

SKIP_OBJECT_FIELDS = {"faction", "factions", "units", "main_units", "mount", "mounts", "battle_entities"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def extract_version(doc: Any, explicit: str = "") -> str:
    if explicit:
        return explicit
    if isinstance(doc, dict):
        root = doc.get("data", {}).get("tww", {})
        for value in (root.get("tww_version"), root.get("version"), doc.get("tww_version"), doc.get("version")):
            if value:
                return str(value)
    return ""


def compact_units(doc: Any) -> List[Dict[str, Any]]:
    if isinstance(doc, list):
        return [x for x in doc if isinstance(x, dict)]
    if isinstance(doc, dict) and isinstance(doc.get("units"), list):
        return [x for x in doc["units"] if isinstance(x, dict)]

    root = doc.get("data", {}).get("tww", {}) if isinstance(doc, dict) else {}
    raw_units = root.get("faction", {}).get("units") if isinstance(root, dict) else None
    if not isinstance(raw_units, list):
        raise SystemExit("Input must be a compact roster list, {units: [...]}, or raw TWWStats faction JSON.")

    out: List[Dict[str, Any]] = []
    for index, unit in enumerate(raw_units, 1):
        if not isinstance(unit, dict):
            continue
        land = unit.get("land_unit") or {}
        variant = land.get("variant") or {}
        group = unit.get("ui_unit_group") or {}
        parent = group.get("parent_group") or {}
        unit_sets = unit.get("unit_sets") or []
        uid = str(unit.get("unit") or unit.get("id") or f"unit_{index:03d}")
        tags: List[str] = []
        if any((x or {}).get("special_category") == "renown" for x in unit_sets):
            tags.append("RoR / Unique")
        if group.get("name"):
            tags.append(str(group["name"]))
        if unit.get("caste"):
            tags.append(str(unit["caste"]))
        out.append(
            {
                "id": uid,
                "n": str(land.get("onscreen_name") or unit.get("name") or uid),
                "c": int(unit.get("multiplayer_cost") or 0),
                "g": str(parent.get("onscreen_name") or group.get("name") or unit.get("caste") or ""),
                "t": dedupe(tags),
                "s": "",
                "image_code": str(variant.get("unit_card_url") or ""),
                "ror": "RoR / Unique" in tags,
            }
        )
    return out


def post_json(endpoint: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://twwstats.com",
            "Referer": "https://twwstats.com/units",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:3000]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def gql(endpoint: str, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    doc = post_json(endpoint, payload)
    if doc.get("errors"):
        raise RuntimeError(json.dumps(doc["errors"], ensure_ascii=False)[:3000])
    return doc


def endpoint_candidates(explicit: str) -> List[str]:
    return dedupe([explicit, os.environ.get("TWWSTATS_GRAPHQL", ""), *ENDPOINTS])


def choose_endpoint(candidates: Sequence[str]) -> str:
    last = ""
    for endpoint in candidates:
        try:
            doc = gql(endpoint, "query Probe { __typename }")
            if doc.get("data", {}).get("__typename"):
                return endpoint
        except Exception as exc:
            last = f"{endpoint}: {exc}"
    raise SystemExit(f"No working GraphQL endpoint found. Last error: {last}")


def unwrap_type(type_ref: Dict[str, Any]) -> Tuple[str, str]:
    node = type_ref
    while isinstance(node, dict) and node.get("ofType"):
        node = node["ofType"]
    return str(node.get("kind") or ""), str(node.get("name") or "")


def is_non_null(type_ref: Dict[str, Any]) -> bool:
    return (type_ref or {}).get("kind") == "NON_NULL"


def graph_arg(value: str, enum: bool = False) -> str:
    return value if enum else json.dumps(value)


class Schema:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.cache: Dict[str, Dict[str, Any]] = {}
        root = gql(endpoint, ROOT_QUERY)
        self.query_type = root["data"]["__schema"]["queryType"]["name"]

    def type(self, name: str) -> Dict[str, Any]:
        if name not in self.cache:
            doc = gql(self.endpoint, TYPE_QUERY, {"name": name})
            value = doc.get("data", {}).get("__type")
            if not value:
                raise KeyError(name)
            self.cache[name] = value
        return self.cache[name]

    def fields(self, name: str) -> List[Dict[str, Any]]:
        return list(self.type(name).get("fields") or [])

    def enum_values(self, name: str) -> List[str]:
        return [x["name"] for x in self.type(name).get("enumValues") or [] if x.get("name")]


def field_return_type(field: Dict[str, Any]) -> Tuple[str, str]:
    return unwrap_type(field.get("type") or {})


def call_field_candidates(schema: Schema, field: Dict[str, Any], values: Sequence[str], arg_hints: Sequence[str]) -> List[str]:
    name = str(field["name"])
    args = list(field.get("args") or [])
    required = [a for a in args if is_non_null(a.get("type") or {})]
    out: List[str] = [] if required else [name]

    hinted = [a for a in args if any(h in str(a.get("name", "")).lower() for h in arg_hints)]
    for arg in hinted or args:
        arg_name = str(arg.get("name") or "")
        kind, type_name = unwrap_type(arg.get("type") or {})
        if kind not in {"SCALAR", "ENUM"} and type_name not in {"String", "ID"}:
            continue
        is_enum = kind == "ENUM"
        arg_values = list(values)
        if is_enum:
            enums = schema.enum_values(type_name)
            arg_values = []
            for value in values:
                normalized = value.lower().replace("-", "_")
                for enum in enums:
                    low = enum.lower()
                    if normalized == low or normalized in low or low in normalized:
                        arg_values.append(enum)
            arg_values.extend(enums[:10])
        for value in dedupe(arg_values):
            out.append(f"{name}({arg_name}: {graph_arg(value, is_enum)})")
    return dedupe(out)


def find_tww_call(schema: Schema, version: str) -> Tuple[str, str]:
    root_fields = schema.fields(schema.query_type)
    field = next((x for x in root_fields if x.get("name") == "tww"), None)
    if not field:
        field = next((x for x in root_fields if "tww" in str(x.get("name", "")).lower()), None)
    if not field:
        raise SystemExit("No tww root field found.")

    values = dedupe([version, "warhammer3", "wh3", "tww3", "total_war_warhammer_3"])
    for call in call_field_candidates(schema, field, values, ("tww", "version", "game")):
        try:
            doc = gql(schema.endpoint, f"query ProbeTww {{ {call} {{ __typename }} }}")
            data = doc.get("data", {}).get(str(field["name"]))
            if isinstance(data, dict) and data.get("__typename"):
                return call, str(data["__typename"])
        except Exception:
            continue
    raise SystemExit("Could not call tww root field with exact version or game aliases.")


def faction_values(faction: str, explicit: str) -> List[str]:
    return dedupe([explicit, *FACTION_GUESSES.get(faction.lower(), []), faction])


def find_faction_units_path(schema: Schema, tww_call: str, tww_type: str, faction: str, faction_value: str) -> Tuple[str, str, str]:
    fields = schema.fields(tww_type)
    faction_field = next((x for x in fields if x.get("name") == "faction"), None)
    if not faction_field:
        faction_field = next((x for x in fields if "faction" in str(x.get("name", "")).lower()), None)
    if not faction_field:
        raise SystemExit("No faction field found under tww root.")

    for faction_call in call_field_candidates(schema, faction_field, faction_values(faction, faction_value), ("faction", "subculture", "key", "id", "name")):
        try:
            query = f"query ProbeFaction {{ {tww_call} {{ {faction_call} {{ __typename units {{ __typename }} }} }} }}"
            doc = gql(schema.endpoint, query)
            tww_data = doc.get("data", {}).get(tww_call.split("(")[0], {})
            faction_data = tww_data.get(str(faction_field["name"]))
            units = faction_data.get("units") if isinstance(faction_data, dict) else None
            if isinstance(units, list):
                unit_type = str(units[0].get("__typename") if units else "main_unit")
                return faction_call, str(faction_field["name"]), unit_type
        except Exception:
            continue

    raise SystemExit("Could not query faction units. Check --tww-version and --faction-value.")


def is_scalar_field(field: Dict[str, Any]) -> bool:
    kind, _name = field_return_type(field)
    return kind in {"SCALAR", "ENUM"} and not field.get("args")


def is_object_field(field: Dict[str, Any]) -> bool:
    kind, _name = field_return_type(field)
    return kind in {"OBJECT", "INTERFACE"} and not field.get("args")


def indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else line for line in text.splitlines())


def build_selection(schema: Schema, type_name: str, depth: int, seen: Tuple[str, ...] = ()) -> str:
    if not type_name or type_name in seen:
        return "__typename"
    pieces = ["__typename"]
    fields = schema.fields(type_name)
    for field in fields:
        name = str(field.get("name") or "")
        if name and not name.startswith("__") and is_scalar_field(field):
            pieces.append(name)
    if depth <= 0:
        return "\n".join(dedupe(pieces))
    for field in fields:
        name = str(field.get("name") or "")
        nested_type = field_return_type(field)[1]
        if not name or name in SKIP_OBJECT_FIELDS or not is_object_field(field) or nested_type in seen:
            continue
        try:
            nested = build_selection(schema, nested_type, depth - 1, (*seen, type_name))
        except Exception:
            continue
        pieces.append(f"{name} {{\n{indent(nested, 2)}\n}}")
    return "\n".join(dedupe(pieces))


def fetch_details(schema: Schema, tww_call: str, faction_call: str, unit_type: str, depth: int) -> Tuple[List[Dict[str, Any]], str]:
    selection = build_selection(schema, unit_type, depth)
    query = f"""
query EnrichUnits {{
  {tww_call} {{
    __typename
    tww_version
    {faction_call} {{
      __typename
      units {{
{indent(selection, 8)}
      }}
    }}
  }}
}}
"""
    try:
        doc = gql(schema.endpoint, query)
    except Exception as exc:
        if depth > 0:
            print(f"Deep query failed, retrying shallow. Error: {exc}", file=sys.stderr)
            return fetch_details(schema, tww_call, faction_call, unit_type, 0)
        raise
    tww_data = doc.get("data", {}).get(tww_call.split("(")[0], {})
    faction_data = tww_data.get(faction_call.split("(")[0], {})
    units = faction_data.get("units") or []
    version = str(tww_data.get("tww_version") or "")
    return [x for x in units if isinstance(x, dict)], version


def normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text or len(text) > 32:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def find_number(obj: Any, field_names: Sequence[str]) -> Optional[float]:
    targets = {normalized_key(x) for x in field_names}
    queue: deque[Any] = deque([obj])
    seen = 0
    while queue and seen < 5000:
        seen += 1
        current = queue.popleft()
        if isinstance(current, dict):
            for key, value in current.items():
                if normalized_key(key) in targets:
                    number = as_number(value)
                    if number is not None:
                        return number
            for value in current.values():
                if isinstance(value, (dict, list)):
                    queue.append(value)
        elif isinstance(current, list):
            for value in current:
                if isinstance(value, (dict, list)):
                    queue.append(value)
    return None


def intish(value: float) -> Any:
    return int(round(value)) if abs(value - round(value)) < 0.00001 else round(value, 3)


def extract_stats(detail: Dict[str, Any]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    for stat, candidates in STAT_CANDIDATES.items():
        value = find_number(detail, candidates)
        if value is not None:
            stats[stat] = intish(value)

    if "weapon_strength" not in stats:
        base = find_number(detail, ("base_weapon_damage", "base_damage", "normal_damage"))
        ap = find_number(detail, ("ap_weapon_damage", "ap_damage", "armour_piercing_damage", "armor_piercing_damage"))
        if base is not None or ap is not None:
            stats["weapon_strength"] = intish((base or 0) + (ap or 0))

    if "missile_strength" not in stats:
        base = find_number(detail, ("base_missile_damage", "base_projectile_damage"))
        ap = find_number(detail, ("ap_missile_damage", "ap_projectile_damage"))
        explosive = find_number(detail, ("explosive_damage", "detonation_damage"))
        if base is not None or ap is not None or explosive is not None:
            stats["missile_strength"] = intish((base or 0) + (ap or 0) + (explosive or 0))
    return stats


def summary(stats: Dict[str, Any]) -> str:
    return " · ".join(f"{label} {stats[key]}" for key, label in SUMMARY_ORDER if key in stats)


def unit_id(unit: Dict[str, Any]) -> str:
    return str(unit.get("unit") or unit.get("id") or unit.get("key") or "")


def unit_name(unit: Dict[str, Any]) -> str:
    land = unit.get("land_unit") or {}
    return str(unit.get("n") or unit.get("name") or unit.get("onscreen_name") or land.get("onscreen_name") or "")


def index_details(details: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}
    for detail in details:
        uid = unit_id(detail)
        name = unit_name(detail)
        if uid:
            by_id[uid] = detail
        if name:
            by_name[normalized_key(name)] = detail
    return by_id, by_name


def enrich(roster: List[Dict[str, Any]], details: List[Dict[str, Any]], compact_only: bool) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
    by_id, by_name = index_details(details)
    out: List[Dict[str, Any]] = []
    missing: List[str] = []
    raw_used: List[Dict[str, Any]] = []

    for unit in roster:
        row = dict(unit)
        detail = by_id.get(str(unit.get("id") or "")) or by_name.get(normalized_key(str(unit.get("n") or "")))
        if not detail:
            missing.append(str(unit.get("id") or unit.get("n") or ""))
            out.append(row)
            continue
        stats = extract_stats(detail)
        stat_summary = summary(stats)
        if stat_summary:
            row["s"] = stat_summary
        if stats and not compact_only:
            row["stats"] = stats
        raw_used.append({"id": row.get("id"), "name": row.get("n"), "summary": stat_summary, "stats": stats, "raw": detail})
        out.append(row)
    return out, missing, raw_used


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--faction", default="norsca")
    parser.add_argument("--faction-value", default="")
    parser.add_argument("--tww-version", default="", help="Exact numeric TWWStats version. Defaults to input JSON data.tww.tww_version.")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--out", default="norsca_roster.enriched.json")
    parser.add_argument("--raw-out", default="")
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--compact-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    doc = load_json(Path(args.input))
    version = extract_version(doc, args.tww_version)
    if not version:
        raise SystemExit("No tww_version found. Pass --tww-version 994043630235584661.")

    roster = compact_units(doc)
    print(f"Input units: {len(roster)}")
    print(f"Faction: {args.faction}")
    print(f"TWW version: {version}")

    endpoint = choose_endpoint(endpoint_candidates(args.endpoint))
    print(f"GraphQL endpoint: {endpoint}")

    schema = Schema(endpoint)
    tww_call, tww_type = find_tww_call(schema, version)
    faction_call, faction_field_name, unit_type = find_faction_units_path(schema, tww_call, tww_type, args.faction, args.faction_value)
    print(f"TWW call: {tww_call}")
    print(f"Faction call: {faction_call}")
    print(f"Unit type: {unit_type}")

    details, resolved_version = fetch_details(schema, tww_call, faction_call, unit_type, max(0, args.max_depth))
    enriched, missing, raw_used = enrich(roster, details, args.compact_only)

    write_json(Path(args.out), enriched)
    if args.raw_out:
        write_json(Path(args.raw_out), {
            "schema": 1,
            "source": "twwstats_graphql",
            "endpoint": endpoint,
            "tww_call": tww_call,
            "faction_call": faction_call,
            "version": resolved_version or version,
            "faction": args.faction,
            "detail_units_fetched": len(details),
            "matched": len(raw_used),
            "missing": missing,
            "units": raw_used,
        })

    with_summary = sum(1 for row in enriched if str(row.get("s") or "").strip())
    print(f"Wrote: {args.out}")
    if args.raw_out:
        print(f"Wrote: {args.raw_out}")
    print(f"Detail units fetched: {len(details)}")
    print(f"Units with summaries: {with_summary}/{len(enriched)}")
    print(f"Missing detail matches: {len(missing)}")
    for row in enriched[:5]:
        print(f"FIRST5 {row.get('id')} | {row.get('n')} | {row.get('s')}")
    return 0 if with_summary else 2


if __name__ == "__main__":
    raise SystemExit(main())
