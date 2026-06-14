#!/usr/bin/env python3
"""
Enrich a compact Total War: Warhammer faction roster from TWWStats GraphQL.

This is a test data-generation script. It does not edit the frontend and it does
not replace roster.json unless you choose that path manually.

Default output:
  factions/<faction>/roster.enriched.json

Typical use:
  python tools/enrich_roster_from_twwstats.py \
    --input factions/norsca/roster.json \
    --faction norsca \
    --out factions/norsca/roster.enriched.json \
    --raw-out factions/norsca/roster.enriched_raw.json

Fast endpoint override, if discovery fails:
  python tools/enrich_roster_from_twwstats.py -i factions/norsca/roster.json \
    --faction norsca \
    --endpoint https://www.twwstats.com/graphql
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


UA = "Mozilla/5.0 RosterEnricher/0.1"
SSL_CONTEXT = ssl._create_unverified_context()
SITE_URLS = ("https://twwstats.com/", "https://www.twwstats.com/")
DEFAULT_ENDPOINTS = (
    "https://twwstats.com/graphql",
    "https://www.twwstats.com/graphql",
    "https://twwstats.com/api/graphql",
    "https://www.twwstats.com/api/graphql",
    "https://api.twwstats.com/graphql",
    "https://api.twwstats.com/",
)

FACTION_VALUE_GUESSES: Dict[str, List[str]] = {
    "norsca": [
        "norsca",
        "nor",
        "wh_dlc08_sc_nor_norsca",
        "wh_main_sc_nor_norsca",
        "wh_dlc08_nor_norsca",
        "wh_main_nor_norsca",
    ],
    "khorne": [
        "khorne",
        "kho",
        "wh3_main_sc_kho_khorne",
        "wh3_main_kho_khorne",
    ],
    "skaven": ["skaven", "skv", "wh2_main_sc_skv_skaven"],
}

TYPE_REF_FRAGMENT = """
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

SCHEMA_QUERY = "query IntrospectSchema { __schema { queryType { name } } }"

TYPE_QUERY = (
    TYPE_REF_FRAGMENT
    + """
query IntrospectType($name: String!) {
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
    enumValues {
      name
    }
  }
}
"""
)

STAT_CANDIDATES: Dict[str, Sequence[str]] = {
    "armour": ("stat_armour", "armour", "armor", "armour_value", "armor_value"),
    "leadership": ("stat_leadership", "leadership", "morale", "stat_morale"),
    "speed": ("stat_speed", "speed", "run_speed"),
    "melee_attack": (
        "stat_melee_attack",
        "melee_attack",
        "meleeattack",
        "melee_attack_value",
    ),
    "melee_defence": (
        "stat_melee_defence",
        "stat_melee_defense",
        "melee_defence",
        "melee_defense",
        "meleedefence",
        "melee_defence_value",
    ),
    "weapon_strength": (
        "stat_weapon_strength",
        "weapon_strength",
        "weaponstrength",
        "melee_weapon_strength",
        "melee_damage",
        "weapon_damage",
        "damage",
    ),
    "charge_bonus": (
        "stat_charge_bonus",
        "charge_bonus",
        "chargebonus",
    ),
    "ammo": ("stat_ammo", "ammo", "ammunition"),
    "range": ("stat_range", "range", "missile_range", "maximum_range"),
    "missile_strength": (
        "stat_missile_strength",
        "missile_strength",
        "missilestrength",
        "projectile_damage",
        "missile_damage",
    ),
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

SKIP_NESTED_FIELD_NAMES = {
    "faction",
    "factions",
    "units",
    "main_units",
    "mounts",
    "mount",
    "battle_entities",
}


class GraphQLError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    return json.loads(text)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compact_units(doc: Any) -> List[Dict[str, Any]]:
    if isinstance(doc, list):
        return [x for x in doc if isinstance(x, dict)]
    if isinstance(doc, dict) and isinstance(doc.get("units"), list):
        return [x for x in doc["units"] if isinstance(x, dict)]
    root = doc.get("data", {}).get("tww", {}) if isinstance(doc, dict) else {}
    units = root.get("faction", {}).get("units") if isinstance(root, dict) else None
    if isinstance(units, list):
        out: List[Dict[str, Any]] = []
        for index, item in enumerate(units, 1):
            if not isinstance(item, dict):
                continue
            land = item.get("land_unit") or {}
            group = item.get("ui_unit_group") or {}
            parent = group.get("parent_group") or {}
            unit_sets = item.get("unit_sets") or []
            uid = str(item.get("unit") or item.get("id") or f"unit_{index:03d}")
            name = str(land.get("onscreen_name") or item.get("name") or uid)
            tags = []
            if any((x or {}).get("special_category") == "renown" for x in unit_sets):
                tags.append("RoR / Unique")
            if group.get("name"):
                tags.append(str(group["name"]))
            if item.get("caste"):
                tags.append(str(item["caste"]))
            out.append(
                {
                    "id": uid,
                    "n": name,
                    "c": int(item.get("multiplayer_cost") or 0),
                    "g": str(parent.get("onscreen_name") or group.get("name") or item.get("caste") or ""),
                    "t": dedupe(tags),
                    "s": "",
                    "image_code": str((land.get("variant") or {}).get("unit_card_url") or ""),
                    "ror": "RoR / Unique" in tags,
                }
            )
        return out
    raise SystemExit("Input must be a compact roster list, {units: [...]}, or TWWStats raw faction JSON.")


def dedupe(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def http_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/javascript,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
        data = resp.read()
    return data.decode("utf-8", "replace")


def http_json_post(endpoint: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
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
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
        raw = resp.read()
        text = raw.decode("utf-8", "replace")
        return json.loads(text)


def gql(endpoint: str, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    doc = http_json_post(endpoint, payload)
    return doc


def gql_checked(endpoint: str, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    doc = gql(endpoint, query, variables)
    if doc.get("errors"):
        raise GraphQLError(json.dumps(doc["errors"], ensure_ascii=False)[:1500])
    return doc


def discover_endpoints(explicit: str = "") -> List[str]:
    found: List[str] = []
    env = os.environ.get("TWWSTATS_GRAPHQL", "").strip()

    for value in (explicit, env, *DEFAULT_ENDPOINTS):
        if value and value not in found:
            found.append(value)

    endpoint_re = re.compile(r"https?://[^\"'\\<>\s]+graphql[^\"'\\<>\s]*|/[A-Za-z0-9_./-]*graphql[A-Za-z0-9_./-]*")
    script_re = re.compile(r"<script[^>]+src=[\"']([^\"']+)[\"']", re.I)

    for site in SITE_URLS:
        try:
            html = http_text(site, timeout=12)
        except Exception:
            continue

        for match in endpoint_re.findall(html):
            url = urllib.parse.urljoin(site, match)
            if url not in found:
                found.append(url)

        scripts = [urllib.parse.urljoin(site, s) for s in script_re.findall(html)]
        for script_url in scripts[:12]:
            try:
                js = http_text(script_url, timeout=18)
            except Exception:
                continue
            for match in endpoint_re.findall(js):
                url = urllib.parse.urljoin(site, match)
                if url not in found:
                    found.append(url)

    return found


def choose_endpoint(candidates: Sequence[str]) -> str:
    last_error = ""
    for endpoint in candidates:
        try:
            doc = gql_checked(endpoint, "query Probe { __typename }")
            if doc.get("data", {}).get("__typename"):
                print(f"GraphQL endpoint: {endpoint}")
                return endpoint
        except Exception as exc:
            last_error = f"{endpoint}: {exc}"
            continue
    raise SystemExit(f"No working TWWStats GraphQL endpoint found. Last error: {last_error}")


def unwrap_type(type_ref: Dict[str, Any]) -> Tuple[str, str]:
    node = type_ref
    while isinstance(node, dict) and node.get("ofType"):
        node = node["ofType"]
    return str(node.get("kind") or ""), str(node.get("name") or "")


def is_required(type_ref: Dict[str, Any]) -> bool:
    return type_ref.get("kind") == "NON_NULL"


def type_name(type_ref: Dict[str, Any]) -> str:
    return unwrap_type(type_ref)[1]


def field_type_kind(field: Dict[str, Any]) -> Tuple[str, str]:
    return unwrap_type(field.get("type") or {})


class Schema:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.cache: Dict[str, Dict[str, Any]] = {}
        doc = gql_checked(endpoint, SCHEMA_QUERY)
        self.query_type = doc["data"]["__schema"]["queryType"]["name"]

    def get_type(self, name: str) -> Dict[str, Any]:
        if not name:
            raise KeyError("empty type name")
        if name not in self.cache:
            doc = gql_checked(self.endpoint, TYPE_QUERY, {"name": name})
            value = doc.get("data", {}).get("__type")
            if not value:
                raise KeyError(f"GraphQL type not found: {name}")
            self.cache[name] = value
        return self.cache[name]

    def fields(self, name: str) -> List[Dict[str, Any]]:
        return list(self.get_type(name).get("fields") or [])

    def field(self, type_name_value: str, field_name: str) -> Optional[Dict[str, Any]]:
        for field in self.fields(type_name_value):
            if field.get("name") == field_name:
                return field
        return None

    def enum_values(self, name: str) -> List[str]:
        info = self.get_type(name)
        return [x["name"] for x in info.get("enumValues") or [] if x.get("name")]


def graphql_arg_literal(value: str, is_enum: bool = False) -> str:
    if is_enum:
        return value
    return json.dumps(value)


def call_candidates_for_field(
    schema: Schema,
    field: Dict[str, Any],
    preferred_values: Sequence[str],
    arg_name_hints: Sequence[str] = (),
) -> List[str]:
    name = str(field["name"])
    args = list(field.get("args") or [])

    if not args:
        return [name]

    required = [a for a in args if is_required(a.get("type") or {})]

    out: List[str] = [name] if not required else []

    candidate_args = args
    if arg_name_hints:
        hinted = [a for a in args if any(h.lower() in a["name"].lower() for h in arg_name_hints)]
        candidate_args = hinted or args

    for arg in candidate_args:
        arg_name = str(arg["name"])
        arg_kind, arg_type_name = unwrap_type(arg.get("type") or {})
        accepts_value = arg_kind in {"SCALAR", "ENUM"} or arg_type_name in {"String", "ID"}
        if not accepts_value:
            continue

        values = list(preferred_values)
        is_enum = arg_kind == "ENUM"
        if is_enum:
            enum_values = schema.enum_values(arg_type_name)
            values = []
            for preferred in preferred_values:
                normalized = preferred.lower().replace("-", "_")
                for enum_value in enum_values:
                    low = enum_value.lower()
                    if normalized == low or normalized in low or low in normalized:
                        values.append(enum_value)
            values.extend(enum_values[:8])

        for value in dedupe(values):
            literal = graphql_arg_literal(value, is_enum=is_enum)
            out.append(f"{name}({arg_name}: {literal})")

    return dedupe(out)


def find_tww_call(schema: Schema) -> Tuple[str, str]:
    query_fields = schema.fields(schema.query_type)
    tww_field = next((f for f in query_fields if f.get("name") == "tww"), None)
    if not tww_field:
        tww_field = next((f for f in query_fields if "tww" in str(f.get("name", "")).lower()), None)
    if not tww_field:
        names = ", ".join(str(f.get("name")) for f in query_fields[:30])
        raise SystemExit(f"Could not find TWW root field. Root fields: {names}")

    game_values = ("warhammer3", "wh3", "tww3", "total_war_warhammer_3")
    for call in call_candidates_for_field(schema, tww_field, game_values, ("game", "version")):
        probe = f"query ProbeTww {{ {call} {{ __typename }} }}"
        try:
            doc = gql_checked(schema.endpoint, probe)
            tww_data = doc.get("data", {}).get(str(tww_field["name"]))
            if isinstance(tww_data, dict) and tww_data.get("__typename"):
                return call, str(tww_data["__typename"])
        except Exception:
            continue
    raise SystemExit("Could not call the TWW GraphQL root field.")


def faction_values(faction: str, explicit: str = "") -> List[str]:
    values: List[str] = []
    if explicit:
        values.append(explicit)
    values.extend(FACTION_VALUE_GUESSES.get(faction.lower(), []))
    values.append(faction)
    return dedupe(values)


def find_units_path(schema: Schema, tww_call: str, tww_type: str, faction: str, faction_value: str) -> Tuple[str, str, str]:
    tww_fields = schema.fields(tww_type)

    direct_units = next((f for f in tww_fields if f.get("name") == "units"), None)
    if direct_units:
        query = f"query ProbeUnits {{ {tww_call} {{ units {{ __typename }} }} }}"
        try:
            doc = gql_checked(schema.endpoint, query)
            units = doc.get("data", {}).get(tww_call.split("(")[0], {}).get("units")
            if isinstance(units, list):
                unit_type = str(units[0].get("__typename") if units else type_name(direct_units.get("type") or {}))
                return "direct", "units", unit_type
        except Exception:
            pass

    faction_field = next((f for f in tww_fields if f.get("name") == "faction"), None)
    if not faction_field:
        faction_field = next((f for f in tww_fields if "faction" in str(f.get("name", "")).lower()), None)

    if not faction_field:
        names = ", ".join(str(f.get("name")) for f in tww_fields[:40])
        raise SystemExit(f"No faction or direct units field found under TWW type. Fields: {names}")

    candidates = call_candidates_for_field(
        schema,
        faction_field,
        faction_values(faction, faction_value),
        ("faction", "key", "id", "name", "subculture"),
    )

    for faction_call in candidates:
        query = f"""
query ProbeFaction {{
  {tww_call} {{
    {faction_call} {{
      __typename
      units {{ __typename unit }}
    }}
  }}
}}
"""
        try:
            doc = gql_checked(schema.endpoint, query)
            tww_data = doc.get("data", {}).get(tww_call.split("(")[0], {})
            faction_data = tww_data.get(str(faction_field["name"]))
            if isinstance(faction_data, dict) and isinstance(faction_data.get("units"), list):
                units = faction_data["units"]
                unit_type = str(units[0].get("__typename") if units else "main_unit")
                return "faction", faction_call, unit_type
        except Exception:
            continue

    raise SystemExit("Could not query TWWStats faction units. Try --faction-value with the exact TWWStats faction/subculture key.")


def is_leaf_field(field: Dict[str, Any]) -> bool:
    kind, _name = field_type_kind(field)
    return kind in {"SCALAR", "ENUM"} and not field.get("args")


def is_objectish_field(field: Dict[str, Any]) -> bool:
    kind, _name = field_type_kind(field)
    return kind in {"OBJECT", "INTERFACE"} and not field.get("args")


def build_selection(schema: Schema, type_name_value: str, depth: int, seen: Optional[Tuple[str, ...]] = None) -> str:
    seen = seen or ()
    if not type_name_value or type_name_value in seen:
        return "__typename"

    pieces: List[str] = ["__typename"]
    fields = schema.fields(type_name_value)

    for field in fields:
        name = str(field.get("name") or "")
        if not name.startswith("__") and is_leaf_field(field):
            pieces.append(name)

    if depth <= 0:
        return "\n".join(dedupe(pieces))

    for field in fields:
        name = str(field.get("name") or "")
        if not name or name in SKIP_NESTED_FIELD_NAMES:
            continue
        if not is_objectish_field(field):
            continue
        nested_type = field_type_kind(field)[1]
        if not nested_type or nested_type in seen:
            continue
        nested_selection = build_selection(schema, nested_type, depth - 1, (*seen, type_name_value))
        if nested_selection.strip():
            pieces.append(f"{name} {{\n{indent(nested_selection, 2)}\n}}")

    return "\n".join(dedupe(pieces))


def indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else line for line in text.splitlines())


def fetch_detail_units(
    schema: Schema,
    tww_call: str,
    path_kind: str,
    units_path: str,
    unit_type: str,
    max_depth: int,
) -> Tuple[List[Dict[str, Any]], str]:
    selection = build_selection(schema, unit_type, max_depth)

    if path_kind == "direct":
        query = f"""
query EnrichUnits {{
  {tww_call} {{
    __typename
    tww_version
    {units_path} {{
{indent(selection, 6)}
    }}
  }}
}}
"""
    else:
        query = f"""
query EnrichFactionUnits {{
  {tww_call} {{
    __typename
    tww_version
    {units_path} {{
      __typename
      units {{
{indent(selection, 8)}
      }}
    }}
  }}
}}
"""

    try:
        doc = gql_checked(schema.endpoint, query)
    except Exception as exc:
        if max_depth > 0:
            print(f"Deep query failed, retrying shallow selection. Error: {exc}", file=sys.stderr)
            return fetch_detail_units(schema, tww_call, path_kind, units_path, unit_type, 0)
        raise

    data = doc.get("data") or {}
    tww_data = data.get(tww_call.split("(")[0]) or {}
    version = str(tww_data.get("tww_version") or "")
    units: List[Dict[str, Any]]
    if path_kind == "direct":
        units = tww_data.get(units_path) or []
    else:
        faction_field_name = units_path.split("(")[0]
        faction_data = tww_data.get(faction_field_name) or {}
        units = faction_data.get("units") or []

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


def find_number(obj: Any, names: Sequence[str]) -> Optional[float]:
    targets = {normalized_key(x) for x in names}
    queue: deque[Any] = deque([obj])
    seen = 0

    while queue and seen < 4000:
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
    if abs(value - round(value)) < 0.00001:
        return int(round(value))
    return round(value, 3)


def extract_stats(detail: Dict[str, Any]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    for stat_key, candidates in STAT_CANDIDATES.items():
        value = find_number(detail, candidates)
        if value is not None:
            stats[stat_key] = intish(value)

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


def summary_from_stats(stats: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key, label in SUMMARY_ORDER:
        if key in stats:
            parts.append(f"{label} {stats[key]}")
    return " · ".join(parts)


def unit_identifier(unit: Dict[str, Any]) -> str:
    return str(unit.get("unit") or unit.get("id") or unit.get("key") or "")


def unit_name(unit: Dict[str, Any]) -> str:
    land = unit.get("land_unit") or {}
    return str(unit.get("n") or unit.get("name") or unit.get("onscreen_name") or land.get("onscreen_name") or "")


def build_detail_index(details: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, Dict[str, Any]] = {}
    for detail in details:
        uid = unit_identifier(detail)
        if uid:
            by_id[uid] = detail
        name = unit_name(detail)
        if name:
            by_name[normalized_key(name)] = detail
    return by_id, by_name


def enrich_units(compact: List[Dict[str, Any]], details: List[Dict[str, Any]], include_stats: bool) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
    by_id, by_name = build_detail_index(details)
    enriched: List[Dict[str, Any]] = []
    missing: List[str] = []
    raw_used: List[Dict[str, Any]] = []

    for unit in compact:
        out = dict(unit)
        uid = str(unit.get("id") or "")
        name = str(unit.get("n") or unit.get("name") or "")
        detail = by_id.get(uid) or by_name.get(normalized_key(name))
        if not detail:
            missing.append(uid or name)
            enriched.append(out)
            continue

        stats = extract_stats(detail)
        summary = summary_from_stats(stats)
        if summary:
            out["s"] = summary
        if include_stats and stats:
            out["stats"] = stats

        raw_used.append({"id": uid, "name": name, "stats": stats, "summary": summary, "raw": detail})
        enriched.append(out)

    return enriched, missing, raw_used


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True, help="Compact roster JSON or raw TWWStats faction JSON.")
    parser.add_argument("--faction", default="norsca", help="Faction slug, e.g. norsca.")
    parser.add_argument("--faction-value", default="", help="Exact TWWStats faction/subculture value if auto-probe fails.")
    parser.add_argument("--endpoint", default="", help="Explicit GraphQL endpoint. Optional.")
    parser.add_argument("--out", default="", help="Output enriched compact roster JSON.")
    parser.add_argument("--raw-out", default="", help="Optional debug file with raw matched TWWStats records.")
    parser.add_argument("--max-depth", type=int, default=2, help="GraphQL nested selection depth. Default: 2.")
    parser.add_argument("--compact-only", action="store_true", help="Only write s summary, not normalized stats object.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Optional delay after endpoint probe.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    doc = load_json(input_path)
    roster = compact_units(doc)

    output_path = Path(args.out or f"factions/{args.faction}/roster.enriched.json")
    raw_output_path = Path(args.raw_out) if args.raw_out else None

    print(f"Input units: {len(roster)}")
    print(f"Faction: {args.faction}")
    print("Discovering TWWStats GraphQL endpoint...")

    endpoint = choose_endpoint(discover_endpoints(args.endpoint))
    if args.sleep:
        time.sleep(args.sleep)

    schema = Schema(endpoint)
    tww_call, tww_type = find_tww_call(schema)
    path_kind, units_path, unit_type = find_units_path(schema, tww_call, tww_type, args.faction, args.faction_value)

    print(f"TWW call: {tww_call}")
    print(f"Units path: {units_path}")
    print(f"Unit type: {unit_type}")

    detail_units, version = fetch_detail_units(schema, tww_call, path_kind, units_path, unit_type, max(0, args.max_depth))
    enriched, missing, raw_used = enrich_units(roster, detail_units, include_stats=not args.compact_only)

    write_json(output_path, enriched)
    if raw_output_path:
        write_json(
            raw_output_path,
            {
                "schema": 1,
                "source": "twwstats_graphql",
                "endpoint": endpoint,
                "version": version,
                "faction": args.faction,
                "matched": len(raw_used),
                "missing": missing,
                "units": raw_used,
            },
        )

    with_summary = sum(1 for unit in enriched if str(unit.get("s") or "").strip())
    print(f"Wrote: {output_path}")
    if raw_output_path:
        print(f"Wrote: {raw_output_path}")
    print(f"Detail units fetched: {len(detail_units)}")
    print(f"Units with summaries: {with_summary}/{len(enriched)}")
    print(f"Missing detail matches: {len(missing)}")
    return 0 if with_summary else 2


if __name__ == "__main__":
    raise SystemExit(main())
