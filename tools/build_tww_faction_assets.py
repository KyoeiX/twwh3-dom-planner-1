#!/usr/bin/env python3
"""
Build Total War: Warhammer faction assets from a TWWStats JSON export.

This replaces faction-specific download scripts.

It does three jobs:
  1) Convert a raw TWWStats roster export into a small frontend roster.json.
  2) Download/verify unit-card images into factions/<faction>/images/.
  3) Write a unit_images_manifest.json so the frontend maps unit id -> image file
     instead of guessing filenames from unit names.

Input shapes supported:
  - Full TWWStats GraphQL export:
      data.tww.tww_version
      data.tww.faction.units[]
  - Condensed export:
      tww_version
      units[]

Example:
  python tools/build_tww_faction_assets.py --input norsca_twwstats_roster.json
  python tools/build_tww_faction_assets.py --input khorne_twwstats_roster.json --faction khorne
  python tools/build_tww_faction_assets.py --input norsca.json --test-count 3
  python tools/build_tww_faction_assets.py --input norsca.json --no-download

Generated:
  factions/
    index.json
    norsca/
      roster.json
      unit_images_manifest.json
      failed_image_downloads.json
      images/
        marauder_champions.webp
        ...
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin


BASE_URL = "https://twwstats.com/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TWWFactionAssetBuilder/2.0"
SSL_CONTEXT = ssl._create_unverified_context()

FACTION_TOKEN_MAP = {
    "kho": ("khorne", "Khorne"),
    "nor": ("norsca", "Norsca"),
    "skv": ("skaven", "Skaven"),
    "emp": ("empire", "Empire"),
    "dwf": ("dwarfs", "Dwarfs"),
    "grn": ("greenskins", "Greenskins"),
    "vmp": ("vampire_counts", "Vampire Counts"),
    "brt": ("bretonnia", "Bretonnia"),
    "hef": ("high_elves", "High Elves"),
    "def": ("dark_elves", "Dark Elves"),
    "lzd": ("lizardmen", "Lizardmen"),
    "tmb": ("tomb_kings", "Tomb Kings"),
    "cst": ("vampire_coast", "Vampire Coast"),
    "ksl": ("kislev", "Kislev"),
    "cth": ("cathay", "Grand Cathay"),
    "ogr": ("ogre_kingdoms", "Ogre Kingdoms"),
    "tze": ("tzeentch", "Tzeentch"),
    "nur": ("nurgle", "Nurgle"),
    "sla": ("slaanesh", "Slaanesh"),
}


PLACEHOLDER_KEYS = {"", "placeholder", "a_character_placeholder", "character_placeholder", "default"}


@dataclass
class ImageResult:
    filename: str = ""
    source_raw: str = ""
    source_url: str = ""
    content_type: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    aspect: Optional[float] = None
    skipped_existing: bool = False


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json_loose(path: Path) -> Dict[str, Any]:
    """Read strict JSON, with a fallback for pasted text that contains leading/trailing junk."""
    text = path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_units(doc: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    if "units" in doc and isinstance(doc["units"], list):
        return str(doc.get("tww_version", "")), list(doc["units"])

    try:
        tww = doc["data"]["tww"]
        return str(tww.get("tww_version", "")), list(tww["faction"]["units"])
    except Exception as exc:
        raise SystemExit(
            "Input JSON must contain either top-level units[] or data.tww.faction.units[]."
        ) from exc


def slug(value: str, max_len: int = 90) -> str:
    value = str(value or "").replace("’", "'").replace("–", "-").replace("—", "-")
    value = value.lower()
    value = re.sub(r"'s\b", "s", value)
    value = re.sub(r"'", "", value)
    value = re.sub(r"[^a-z0-9()_-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return (value[:max_len].strip("_") or "unit")


def title_from_slug(value: str) -> str:
    return re.sub(r"[_-]+", " ", value).strip().title()


def infer_faction_from_filename(path: Path) -> Optional[Tuple[str, str]]:
    stem = slug(path.stem)
    for marker in ("_twwstats", "_unit", "_roster", "_export", "_images"):
        if marker in stem:
            stem = stem.split(marker)[0]
            break
    if stem and not stem.startswith("pasted_text") and stem not in {"units", "roster", "export"}:
        return stem, title_from_slug(stem)
    return None


def infer_faction_from_units(units: List[Dict[str, Any]]) -> Tuple[str, str]:
    counts: Dict[str, int] = {}
    for unit in units:
        uid = str(unit.get("unit") or unit.get("id") or "")
        for token in re.findall(r"(?:^|_)([a-z]{3})(?:_|$)", uid):
            counts[token] = counts.get(token, 0) + 1

    if counts:
        token = max(counts, key=counts.get)
        if token in FACTION_TOKEN_MAP:
            return FACTION_TOKEN_MAP[token]
        return token, title_from_slug(token)

    return "unknown", "Unknown"


def infer_faction(path: Path, units: List[Dict[str, Any]], explicit: str = "") -> Tuple[str, str]:
    if explicit:
        fid = slug(explicit)
        return fid, title_from_slug(fid)

    by_name = infer_faction_from_filename(path)
    if by_name:
        return by_name

    return infer_faction_from_units(units)


def unit_id(unit: Dict[str, Any], index: int) -> str:
    return str(unit.get("unit") or unit.get("id") or unit.get("key") or f"unit_{index:03d}")


def land_unit(unit: Dict[str, Any]) -> Dict[str, Any]:
    return unit.get("land_unit") or {}


def unit_name(unit: Dict[str, Any], index: int) -> str:
    return (
        unit.get("n")
        or unit.get("name")
        or unit.get("onscreen_name")
        or land_unit(unit).get("onscreen_name")
        or unit_id(unit, index)
    )


def variant_key(unit: Dict[str, Any]) -> str:
    return str(((land_unit(unit).get("variant") or {}).get("unit_card_url")) or unit.get("unit_card_url") or "")


def first_general_portrait(unit: Dict[str, Any]) -> str:
    for perm in unit.get("custom_battle_permissions") or []:
        value = (perm or {}).get("general_portrait") or ""
        if value:
            return str(value)
    return ""


def permissions(unit: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [p for p in (unit.get("custom_battle_permissions") or []) if isinstance(p, dict)]


def is_general(unit: Dict[str, Any]) -> bool:
    if str(unit.get("caste") or "").lower() == "lord":
        return True
    return any(bool(p.get("general_unit")) for p in permissions(unit))


def is_hero(unit: Dict[str, Any]) -> bool:
    if str(unit.get("caste") or "").lower() == "hero":
        return True
    parent = (((unit.get("ui_unit_group") or {}).get("parent_group") or {}).get("key") or "")
    return parent == "heroes_agents"


def is_campaign_exclusive(unit: Dict[str, Any]) -> bool:
    perms = permissions(unit)
    if not perms:
        return False
    return any(bool(p.get("campaign_exclusive")) for p in perms)


def is_renown(unit: Dict[str, Any]) -> bool:
    uid = str(unit.get("unit") or unit.get("id") or "")
    if "_ror" in uid:
        return True
    for item in unit.get("unit_sets") or []:
        if (item or {}).get("special_category") == "renown":
            return True
    return False


def parent_group_name(unit: Dict[str, Any]) -> str:
    group = unit.get("ui_unit_group") or {}
    parent = group.get("parent_group") or {}
    return str(parent.get("onscreen_name") or group.get("name") or unit.get("caste") or "Other")


def normalized_group(unit: Dict[str, Any]) -> str:
    if is_general(unit):
        return "Lords"
    if is_hero(unit):
        return "Heroes"
    return parent_group_name(unit)


def unit_tags(unit: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    subgroup = str((unit.get("ui_unit_group") or {}).get("name") or "")
    caste = str(unit.get("caste") or "")

    for value in (subgroup, caste):
        if value and value not in tags and value not in {"Generic"}:
            tags.append(value)

    if is_renown(unit):
        tags.insert(0, "RoR / Unique")
    if is_campaign_exclusive(unit):
        tags.append("Campaign Exclusive")

    return tags[:5]


def stat_line(unit: Dict[str, Any]) -> str:
    # Keep existing condensed stat string if already present.
    for key in ("s", "stats", "stat_line"):
        value = unit.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def ext_from_url(url: str) -> str:
    match = re.search(r"\.([a-zA-Z0-9]+)(?:\?|$)", url)
    ext = ("." + match.group(1).lower()) if match else ".webp"
    if ext in {".jpeg"}:
        ext = ".jpg"
    return ext


def ext_from_ctype(ctype: str, fallback: str = ".webp") -> str:
    ctype = (ctype or "").lower()
    if "webp" in ctype:
        return ".webp"
    if "png" in ctype:
        return ".png"
    if "jpeg" in ctype or "jpg" in ctype:
        return ".jpg"
    return fallback


def replace_ext(path: str, ext: str) -> str:
    return re.sub(r"\.[a-zA-Z0-9]+$", ext, path)


def add_unique(items: List[str], value: str) -> None:
    value = str(value or "").strip()
    if value and value not in items:
        items.append(value)


def candidate_paths(unit: Dict[str, Any]) -> List[str]:
    out: List[str] = []

    for value in unit.get("image_candidate_urls") or []:
        add_unique(out, str(value))
    for value in unit.get("image_candidate_paths") or []:
        add_unique(out, str(value))

    for key in ("image", "img", "image_url", "unit_card_url"):
        value = unit.get(key)
        if value and str(value) not in PLACEHOLDER_KEYS:
            add_unique(out, str(value))

    card = variant_key(unit)
    uid = str(unit.get("unit") or unit.get("id") or "")

    # Normal unit card codes are usually not URLs; TWWStats serves them under ui/units/icons.
    for key in (card, uid):
        if key and key not in PLACEHOLDER_KEYS:
            add_unique(out, f"ui/units/icons/{key}.webp")
            add_unique(out, f"ui/units/icons/{key}.png")
            add_unique(out, f"ui/portraits/units/no_culture/{key}.webp")
            add_unique(out, f"ui/portraits/units/no_culture/{key}.png")

    # Characters often have a placeholder unit card but a porthole portrait.
    gp = first_general_portrait(unit)
    if gp:
        gp = gp.lstrip("/")
        gp_webp = replace_ext(gp, ".webp")
        add_unique(out, gp_webp.replace("/portholes/", "/units/"))
        add_unique(out, gp.replace("/portholes/", "/units/"))
        add_unique(out, gp_webp)
        add_unique(out, gp)

    return out


def resolve_url(raw: str, base_url: str) -> str:
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return urljoin(base_url.rstrip("/") + "/", raw.lstrip("/"))


def fetch_image(url: str, timeout: int = 25) -> Tuple[bool, bytes, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            status = getattr(resp, "status", 200)
            ctype = resp.headers.get("Content-Type", "")
            data = resp.read()
            if status == 200 and ctype.lower().startswith("image/") and len(data) > 100:
                return True, data, ctype, ""
            return False, data, ctype, f"status={status}, content-type={ctype}, bytes={len(data)}"
    except urllib.error.HTTPError as exc:
        return False, b"", "", f"HTTP {exc.code}"
    except Exception as exc:
        return False, b"", "", repr(exc)


def verify_image(path: Path) -> Tuple[bool, str, Optional[int], Optional[int]]:
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as img:
            width, height = img.size
            img.verify()
        return True, "Pillow verified", int(width), int(height)
    except ImportError:
        head = path.read_bytes()[:16]
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return True, "PNG signature verified", None, None
        if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
            return True, "WEBP signature verified", None, None
        if head.startswith(b"\xff\xd8\xff"):
            return True, "JPEG signature verified", None, None
        return False, "unknown image signature", None, None
    except Exception as exc:
        return False, repr(exc), None, None


def image_code_for_unit(norm: Dict[str, Any], unit: Dict[str, Any], mode: str) -> str:
    name_slug = slug(norm["n"])
    card = slug(variant_key(unit))
    uid = slug(norm["id"])

    if mode == "unit-id":
        return uid
    if mode == "image-code" and card and card not in PLACEHOLDER_KEYS:
        return card
    if mode == "name-code" and card and card not in PLACEHOLDER_KEYS:
        return slug(f"{name_slug}_{card}", 130)
    return name_slug


def allocate_code(base_code: str, used: Dict[str, str], uid: str) -> str:
    code = base_code
    n = 2
    while code in used and used[code] != uid:
        code = f"{base_code}_{n}"
        n += 1
    used[code] = uid
    return code


def existing_image_for_code(images_dir: Path, image_code: str) -> Optional[Path]:
    for ext in (".webp", ".png", ".jpg", ".jpeg"):
        path = images_dir / f"{image_code}{ext}"
        if path.exists():
            return path
    return None


def normalize_units(
    raw_units: List[Dict[str, Any]],
    include_campaign_exclusive: bool,
    filename_mode: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, str], int]:
    roster: List[Dict[str, Any]] = []
    used_codes: Dict[str, str] = {}
    skipped_campaign = 0

    for index, unit in enumerate(raw_units, 1):
        if is_campaign_exclusive(unit) and not include_campaign_exclusive:
            skipped_campaign += 1
            continue

        uid = unit_id(unit, index)
        norm = {
            "id": uid,
            "n": unit_name(unit, index),
            "c": int(unit.get("c") or unit.get("cost") or unit.get("multiplayer_cost") or 0),
            "g": normalized_group(unit),
            "t": unit_tags(unit),
            "s": stat_line(unit),
            "image_code": "",
            "ror": is_renown(unit),
            "campaign_exclusive": is_campaign_exclusive(unit),
            "source": {
                "variant_unit_card_url": variant_key(unit),
                "caste": unit.get("caste"),
                "tier": unit.get("tier"),
                "mount_name": unit.get("mount_name"),
                "ui_unit_group": unit.get("ui_unit_group"),
            },
        }
        code = allocate_code(image_code_for_unit(norm, unit, filename_mode), used_codes, uid)
        norm["image_code"] = code
        roster.append(norm)

    roster.sort(key=lambda u: (
        {"Lords": 1, "Heroes": 2, "Infantry": 3, "Missile Infantry": 4, "Cavalry & Chariots": 5, "Missile Cavalry & Chariots": 6, "Monsters & Beasts": 7}.get(u["g"], 99),
        u["c"],
        u["n"],
    ))
    return roster, used_codes, skipped_campaign


def unit_lookup(raw_units: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for index, unit in enumerate(raw_units, 1):
        out[unit_id(unit, index)] = unit
    return out


def download_unit_image(
    unit: Dict[str, Any],
    norm: Dict[str, Any],
    images_dir: Path,
    base_url: str,
    refresh_existing: bool,
    test: bool,
    probe_only: bool,
) -> Tuple[Optional[ImageResult], List[Dict[str, str]]]:
    code = norm["image_code"]
    errors: List[Dict[str, str]] = []

    if not refresh_existing:
        existing = existing_image_for_code(images_dir, code)
        if existing:
            ok, msg, width, height = verify_image(existing)
            if ok:
                return ImageResult(
                    filename=existing.name,
                    width=width,
                    height=height,
                    aspect=round(width / height, 6) if width and height else None,
                    skipped_existing=True,
                ), errors
            errors.append({"url": str(existing), "error": f"existing file failed verification: {msg}"})

    candidates = candidate_paths(unit)
    if test:
        print(f"\nTEST: {norm['n']}")
        print(f"Unit id: {norm['id']}")
        print(f"Image code: {code}")
        if candidates:
            print(f"Raw image value: {candidates[0]}")
            print(f"Resolved URL: {resolve_url(candidates[0], base_url)}")
        else:
            print("No image candidates")

    for raw in candidates:
        url = resolve_url(raw, base_url)
        ok, data, ctype, err = fetch_image(url)
        if not ok:
            errors.append({"url": url, "error": err})
            continue

        ext = ext_from_ctype(ctype, ext_from_url(url))
        filename = f"{code}{ext}"
        target = images_dir / filename

        if probe_only:
            return ImageResult(filename=filename, source_raw=raw, source_url=url, content_type=ctype), errors

        images_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

        ok_open, open_msg, width, height = verify_image(target)
        if not ok_open:
            errors.append({"url": url, "error": f"downloaded file failed verification: {open_msg}"})
            try:
                target.unlink()
            except OSError:
                pass
            continue

        if test:
            print(f"Output filename: {filename}")
            print(f"Verified dimensions: {width}x{height}" if width and height else f"Verified: {open_msg}")

        return ImageResult(
            filename=filename,
            source_raw=raw,
            source_url=url,
            content_type=ctype,
            width=width,
            height=height,
            aspect=round(width / height, 6) if width and height else None,
        ), errors

    return None, errors


def update_registry(registry_path: Path, faction_id: str, faction_name: str) -> None:
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except Exception:
            registry = {}
    else:
        registry = {}

    registry.setdefault("schema", 1)
    registry.setdefault("defaultFaction", faction_id)
    factions = registry.setdefault("factions", [])

    entry = {
        "id": faction_id,
        "name": faction_name,
        "roster": f"/factions/{faction_id}/roster.json",
        "manifest": f"/factions/{faction_id}/unit_images_manifest.json",
        "imageBase": f"/factions/{faction_id}/images/",
        "storageKey": f"armyBuilder:{faction_id}",
    }

    replaced = False
    for i, item in enumerate(factions):
        if item.get("id") == faction_id:
            factions[i] = entry
            replaced = True
            break
    if not replaced:
        factions.append(entry)

    factions.sort(key=lambda x: x.get("name", x.get("id", "")))
    write_json(registry_path, registry)


def write_zip(folder: Path, zip_path: Path) -> None:
    if not folder.exists():
        return
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path != zip_path:
                zf.write(path, path.relative_to(folder))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", "-i", required=True, help="Raw TWWStats JSON export")
    ap.add_argument("--faction", default="", help="Faction slug override, e.g. norsca")
    ap.add_argument("--out-root", default="factions", help="Output root folder")
    ap.add_argument("--registry", default="factions/index.json", help="Faction registry JSON path")
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--filename-mode", choices=["name", "image-code", "unit-id", "name-code"], default="name")
    ap.add_argument("--include-campaign-exclusive", action="store_true")
    ap.add_argument("--no-download", action="store_true", help="Only write roster/manifest shell; do not fetch images")
    ap.add_argument("--probe-only", action="store_true", help="Resolve/test downloads but do not write image files")
    ap.add_argument("--refresh-existing", action="store_true")
    ap.add_argument("--test-count", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.08)
    ap.add_argument("--zip", action="store_true", help="Write a zip of the faction output folder")
    args = ap.parse_args()

    input_path = Path(args.input)
    doc = read_json_loose(input_path)
    version, raw_units = get_units(doc)
    if args.limit:
        raw_units = raw_units[: args.limit]

    faction_id, faction_name = infer_faction(input_path, raw_units, args.faction)

    out_root = Path(args.out_root)
    faction_dir = out_root / faction_id
    images_dir = faction_dir / "images"
    registry_path = Path(args.registry)

    roster, _used_codes, skipped_campaign = normalize_units(
        raw_units,
        include_campaign_exclusive=args.include_campaign_exclusive,
        filename_mode=args.filename_mode,
    )
    raw_by_id = unit_lookup(raw_units)

    print(f"Faction: {faction_name} ({faction_id})")
    print(f"TWW version: {version}")
    print(f"Raw units found: {len(raw_units)}")
    print(f"Roster units written: {len(roster)}")
    if skipped_campaign:
        print(f"Campaign-exclusive skipped: {skipped_campaign}")
    print(f"Output folder: {faction_dir}")

    manifest_by_id: Dict[str, Dict[str, Any]] = {}
    failed: List[Dict[str, Any]] = []

    if not args.no_download:
        for idx, norm in enumerate(roster, 1):
            raw = raw_by_id.get(norm["id"], {})
            result, errors = download_unit_image(
                raw,
                norm,
                images_dir=images_dir,
                base_url=args.base_url,
                refresh_existing=args.refresh_existing,
                test=bool(args.test_count and idx <= args.test_count),
                probe_only=args.probe_only,
            )

            if result:
                manifest_by_id[norm["id"]] = {
                    "id": norm["id"],
                    "name": norm["n"],
                    "image_code": norm["image_code"],
                    "filename": result.filename,
                    "source_raw": result.source_raw,
                    "source_url": result.source_url,
                    "content_type": result.content_type,
                    "width": result.width,
                    "height": result.height,
                    "aspect": result.aspect,
                    "skipped_existing": result.skipped_existing,
                }
                print(f"[{idx:03d}/{len(roster)}] {'SKIP' if result.skipped_existing else 'OK  '} {norm['n']} -> {result.filename}")
            else:
                failed.append({"id": norm["id"], "name": norm["n"], "image_code": norm["image_code"], "tried": errors[:10]})
                print(f"[{idx:03d}/{len(roster)}] MISS {norm['n']}")

            time.sleep(args.sleep)

    # Keep roster small and frontend-friendly. Images are resolved by id through the manifest.
    write_json(faction_dir / "roster.json", roster)

    manifest = {
        "schema": 1,
        "generated_at": now_iso(),
        "faction": {"id": faction_id, "name": faction_name},
        "tww_version": version,
        "image_base": f"/factions/{faction_id}/images/",
        "by_unit_id": manifest_by_id,
        "units": [manifest_by_id[unit["id"]] for unit in roster if unit["id"] in manifest_by_id],
    }
    write_json(faction_dir / "unit_images_manifest.json", manifest)
    write_json(faction_dir / "failed_image_downloads.json", failed)

    update_registry(registry_path, faction_id, faction_name)

    if args.zip:
        zip_path = faction_dir / f"{faction_id}_faction_assets.zip"
        write_zip(faction_dir, zip_path)
        print(f"ZIP written: {zip_path}")

    print(f"\nWrote: {faction_dir / 'roster.json'}")
    print(f"Wrote: {faction_dir / 'unit_images_manifest.json'}")
    print(f"Wrote: {registry_path}")
    print(f"Image successes: {len(manifest_by_id)}")
    print(f"Image failures:  {len(failed)}")

    return 0 if roster else 2


if __name__ == "__main__":
    raise SystemExit(main())
