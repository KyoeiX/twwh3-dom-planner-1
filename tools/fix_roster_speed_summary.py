#!/usr/bin/env python3
"""
Fix TWWStats raw speed scale in enriched roster JSON.

TWWStats may output speed as 3.5, 5.4, 9.5 while the game card/UI expects
35, 54, 95. This post-processes an already generated roster file so Codex does
not need to rerun the GraphQL enrichment.

Usage:
  python tools/fix_roster_speed_summary.py --input norsca_roster.enriched.json --out norsca_roster.fixed.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict

SPD_RE = re.compile(r"\bSpd\s+([0-9]+(?:\.[0-9]+)?)\b")


def normalize_speed(value: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number < 20:
        return int(round(number * 10))
    return int(round(number)) if abs(number - round(number)) < 0.00001 else number


def fix_summary(summary: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return f"Spd {normalize_speed(match.group(1))}"
    return SPD_RE.sub(repl, summary or "")


def fix_unit(unit: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(unit)
    if isinstance(out.get("s"), str):
        out["s"] = fix_summary(out["s"])
    stats = out.get("stats")
    if isinstance(stats, dict) and "speed" in stats:
        out["stats"] = dict(stats)
        out["stats"]["speed"] = normalize_speed(out["stats"]["speed"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--out", "-o", required=True)
    args = parser.parse_args()

    source = Path(args.input)
    target = Path(args.out)
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise SystemExit("Expected enriched roster JSON to be a list of units.")

    fixed = [fix_unit(unit) if isinstance(unit, dict) else unit for unit in data]
    target.write_text(json.dumps(fixed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Read: {source}")
    print(f"Wrote: {target}")
    print(f"Units: {len(fixed)}")
    for row in fixed[:5]:
        if isinstance(row, dict):
            print(f"FIRST5 {row.get('id')} | {row.get('n')} | {row.get('s')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
