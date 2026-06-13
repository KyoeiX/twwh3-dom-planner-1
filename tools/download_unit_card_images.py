#!/usr/bin/env python3
"""
Download unit-card images from a raw faction roster JSON and write a frontend-safe manifest.

Use this for any faction. It only creates an image folder and a manifest.
It does not edit the frontend.

Examples:
  python tools/download_unit_card_images.py --input norsca_roster_raw.json --faction norsca --test-count 3
  python tools/download_unit_card_images.py --input norsca_roster_raw.json --faction norsca
  python tools/download_unit_card_images.py --input khorne_roster_raw.json --faction khorne

Output:
  <faction>_unit_card_images/
    <image_code>.webp
    unit_images_manifest.json
    failed_image_downloads.json
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

DEFAULT_BASE_URL = "https://twwstats.com/"
UA = "Mozilla/5.0 UnitCardDownloader/1.0"
SSL_CONTEXT = ssl._create_unverified_context()
PLACEHOLDERS = {"", "placeholder", "a_character_placeholder", "character_placeholder", "default"}
FACTION_TOKENS = {"kho":"khorne","nor":"norsca","skv":"skaven","emp":"empire","dwf":"dwarfs","grn":"greenskins","vmp":"vampire_counts","brt":"bretonnia","hef":"high_elves","def":"dark_elves","lzd":"lizardmen","tmb":"tomb_kings","cst":"vampire_coast","ksl":"kislev","cth":"grand_cathay","ogr":"ogre_kingdoms","tze":"tzeentch","nur":"nurgle","sla":"slaanesh"}


def load_json(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def get_units(doc: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    if isinstance(doc.get("units"), list):
        return str(doc.get("version", doc.get("tww_version", ""))), list(doc["units"])
    root = doc.get("data", {}).get("tww", {})
    if root:
        return str(root.get("tww_version", root.get("version", ""))), list(root["faction"]["units"])
    raise SystemExit("Input JSON must contain either units[] or data.tww.faction.units[].")


def slug(value: str, max_len: int = 110) -> str:
    value = str(value or "").replace("’", "'").replace("–", "-").replace("—", "-").lower()
    value = re.sub(r"'s\b", "s", value).replace("'", "")
    value = re.sub(r"[^a-z0-9()_-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:max_len].strip("_") or "unit"


def detect_faction(path: Path, units: List[Dict[str, Any]], override: str = "") -> str:
    if override:
        return slug(override)
    stem = slug(path.stem)
    for cut in ("_roster", "_unit", "_export", "_images", "_raw"):
        if cut in stem:
            stem = stem.split(cut)[0]
            break
    if stem and not stem.startswith("pasted_text") and stem not in {"roster", "units", "export"}:
        return stem
    counts: Dict[str, int] = {}
    for unit in units:
        uid = str(unit.get("unit") or unit.get("id") or "")
        for token in re.findall(r"(?:^|_)([a-z]{3})(?:_|$)", uid):
            counts[token] = counts.get(token, 0) + 1
    if counts:
        best = max(counts, key=counts.get)
        return FACTION_TOKENS.get(best, best)
    return "unknown"


def unit_id(unit: Dict[str, Any], index: int) -> str:
    return str(unit.get("unit") or unit.get("id") or unit.get("key") or f"unit_{index:03d}")


def unit_name(unit: Dict[str, Any], index: int) -> str:
    land = unit.get("land_unit") or {}
    return str(unit.get("n") or unit.get("name") or unit.get("onscreen_name") or land.get("onscreen_name") or unit_id(unit, index))


def card_code(unit: Dict[str, Any]) -> str:
    land = unit.get("land_unit") or {}
    variant = land.get("variant") or {}
    return str(variant.get("unit_card_url") or unit.get("unit_card_url") or unit.get("image_code") or "")


def general_portrait(unit: Dict[str, Any]) -> str:
    for perm in unit.get("custom_battle_permissions") or []:
        value = (perm or {}).get("general_portrait") or ""
        if value:
            return str(value)
    return ""


def replace_ext(path: str, ext: str) -> str:
    return re.sub(r"\.[a-zA-Z0-9]+$", ext, path) if re.search(r"\.[a-zA-Z0-9]+$", path) else path + ext


def add_unique(items: List[str], value: str) -> None:
    value = str(value or "").strip()
    if value and value not in items:
        items.append(value)


def image_candidates(unit: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for field in ("image_candidate_urls", "image_candidate_paths"):
        for value in unit.get(field) or []:
            add_unique(out, str(value))
    for field in ("image", "img", "image_url", "unit_card_url"):
        value = unit.get(field)
        if value and str(value) not in PLACEHOLDERS:
            add_unique(out, str(value))
    code = card_code(unit)
    if code and code not in PLACEHOLDERS:
        add_unique(out, f"ui/units/icons/{code}.webp")
        add_unique(out, f"ui/units/icons/{code}.png")
        add_unique(out, f"ui/portraits/units/no_culture/{code}.webp")
        add_unique(out, f"ui/portraits/units/no_culture/{code}.png")
    portrait = general_portrait(unit)
    if portrait:
        portrait = portrait.lstrip("/")
        portrait_webp = replace_ext(portrait, ".webp")
        add_unique(out, portrait_webp.replace("/portholes/", "/units/"))
        add_unique(out, portrait.replace("/portholes/", "/units/"))
        add_unique(out, portrait_webp)
        add_unique(out, portrait)
    return out


def resolve_url(raw: str, base_url: str) -> str:
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return urljoin(base_url.rstrip("/") + "/", raw.lstrip("/"))


def ext_from_url(url: str) -> str:
    match = re.search(r"\.([a-zA-Z0-9]+)(?:\?|$)", url)
    return "." + match.group(1).lower() if match else ".webp"


def ext_from_content_type(content_type: str, fallback: str) -> str:
    ct = (content_type or "").lower()
    if "webp" in ct:
        return ".webp"
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    return fallback


def fetch_image(url: str, timeout: int = 25) -> Tuple[bool, bytes, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            status = getattr(resp, "status", 200)
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read()
            if status == 200 and content_type.lower().startswith("image/") and len(data) > 100:
                return True, data, content_type, ""
            return False, data, content_type, f"status={status}, content-type={content_type}, bytes={len(data)}"
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


def image_code(unit: Dict[str, Any], uid: str, name: str) -> str:
    code = card_code(unit)
    if code and code not in PLACEHOLDERS:
        return slug(code)
    return slug(uid or name)


def existing_image(output_dir: Path, code: str) -> Optional[Path]:
    for ext in (".webp", ".png", ".jpg", ".jpeg"):
        path = output_dir / f"{code}{ext}"
        if path.exists():
            return path
    return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True, help="Raw faction roster JSON")
    parser.add_argument("--faction", default="", help="Faction slug, e.g. norsca. Auto-detected if omitted.")
    parser.add_argument("--out", default="", help="Output folder. Default: <faction>_unit_card_images")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--test-count", type=int, default=0, help="Print detailed URL info for first N units")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--refresh-existing", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.08)
    args = parser.parse_args()

    input_path = Path(args.input)
    doc = load_json(input_path)
    data_version, units = get_units(doc)
    if args.limit:
        units = units[:args.limit]

    faction = detect_faction(input_path, units, args.faction)
    output_dir = Path(args.out or f"{faction}_unit_card_images")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, Any] = {"schema": 1, "faction": faction, "version": data_version, "image_base": f"../{output_dir.name}/", "by_unit_id": {}, "units": []}
    failed: List[Dict[str, Any]] = []
    used_codes: Dict[str, str] = {}

    print(f"Faction: {faction}")
    print(f"Units found: {len(units)}")
    print(f"Output: {output_dir}")

    for index, unit in enumerate(units, 1):
        uid = unit_id(unit, index)
        name = unit_name(unit, index)
        base_code = image_code(unit, uid, name)
        code = base_code
        suffix = 2
        while code in used_codes and used_codes[code] != uid:
            code = f"{base_code}_{suffix}"
            suffix += 1
        used_codes[code] = uid

        candidates = image_candidates(unit)
        if args.test_count and index <= args.test_count:
            print(f"\nTEST {index}")
            print(f"Unit name: {name}")
            print(f"Unit id: {uid}")
            print(f"Image code: {code}")
            if candidates:
                print(f"Raw image value: {candidates[0]}")
                print(f"Resolved URL: {resolve_url(candidates[0], args.base_url)}")

        old = existing_image(output_dir, code)
        if old and not args.refresh_existing:
            ok, msg, width, height = verify_image(old)
            if ok:
                item = {"id": uid, "name": name, "image_code": code, "filename": old.name, "width": width, "height": height, "aspect": round(width / height, 6) if width and height else None, "skipped_existing": True}
                manifest["by_unit_id"][uid] = item
                manifest["units"].append(item)
                print(f"[{index:03d}/{len(units)}] SKIP {name} -> {old.name}")
                continue

        errors: List[Dict[str, str]] = []
        saved = None
        for raw in candidates:
            url = resolve_url(raw, args.base_url)
            ok, data, content_type, err = fetch_image(url)
            if not ok:
                errors.append({"url": url, "error": err})
                continue
            ext = ext_from_content_type(content_type, ext_from_url(url))
            target = output_dir / f"{code}{ext}"
            target.write_bytes(data)
            ok_open, open_msg, width, height = verify_image(target)
            if not ok_open:
                errors.append({"url": url, "error": f"verification failed: {open_msg}"})
                target.unlink(missing_ok=True)
                continue
            saved = {"id": uid, "name": name, "image_code": code, "filename": target.name, "source_raw": raw, "source_url": url, "content_type": content_type, "width": width, "height": height, "aspect": round(width / height, 6) if width and height else None}
            if args.test_count and index <= args.test_count:
                print(f"Output filename: {target.name}")
                print(f"Verified: {width}x{height}" if width and height else f"Verified: {open_msg}")
            break

        if saved:
            manifest["by_unit_id"][uid] = saved
            manifest["units"].append(saved)
            print(f"[{index:03d}/{len(units)}] OK   {name} -> {saved['filename']}")
        else:
            failed.append({"id": uid, "name": name, "image_code": code, "tried": errors[:10]})
            print(f"[{index:03d}/{len(units)}] MISS {name}")

        time.sleep(args.sleep)

    write_json(output_dir / "unit_images_manifest.json", manifest)
    write_json(output_dir / "failed_image_downloads.json", failed)
    print(f"\nWrote: {output_dir / 'unit_images_manifest.json'}")
    print(f"Wrote: {output_dir / 'failed_image_downloads.json'}")
    print(f"Success: {len(manifest['units'])}")
    print(f"Failed:  {len(failed)}")
    return 0 if manifest["units"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
