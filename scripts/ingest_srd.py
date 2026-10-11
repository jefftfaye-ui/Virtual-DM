"""Ingest SRD content into srd_chunks.

Source: 5e-bits/5e-database (CC-BY-4.0, SRD-only content).
  5.1: https://github.com/5e-bits/5e-database
  5.2: Run with --edition 2024 --from <path> once a structured conversion exists.
       The official 5.2 SRD PDF is CC-BY-4.0; extract manually if needed.

Usage:
    # Download + ingest 5.1 from the network (requires internet):
    python scripts/ingest_srd.py --edition 2014

    # Ingest from a local directory of JSON files:
    python scripts/ingest_srd.py --edition 2014 --from /path/to/5e-database/src

    # Wipe existing rows and re-ingest (idempotent):
    python scripts/ingest_srd.py --edition 2014 --wipe

Requires: SUPABASE_URL env var.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import re
from pathlib import Path
from typing import Any

import psycopg

from rules.statblock import (
    normalize_name,
    extract_monster_meta,
    format_monster_body,
    format_spell_body,
    format_condition_body,
    format_rule_body,
    format_equipment_body,
)

# Raw GitHub URLs for 5e-bits/5e-database (5.1 SRD only)
_BASE_2014 = "https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2014/en"
_BASE_2024 = "https://raw.githubusercontent.com/5e-bits/5e-database/main/src/2024/en"
_SOURCES = {
    "2014": {
        "monster":   f"{_BASE_2014}/5e-SRD-Monsters.json",
        "spell":     f"{_BASE_2014}/5e-SRD-Spells.json",
        "condition": f"{_BASE_2014}/5e-SRD-Conditions.json",
        "rule":      f"{_BASE_2014}/5e-SRD-Rules.json",
        "item":      f"{_BASE_2014}/5e-SRD-Equipment.json",
    },
    "2024": {
        "monster":   f"{_BASE_2024}/5e-SRD-Monsters.json",
        "spell":     f"{_BASE_2024}/5e-SRD-Spells.json",
        "condition": f"{_BASE_2024}/5e-SRD-Conditions.json",
        "rule":      f"{_BASE_2024}/5e-SRD-Rules.json",
        "item":      f"{_BASE_2024}/5e-SRD-Equipment.json",
    },
}
_LOCAL_NAMES = {
    "monster":   "5e-SRD-Monsters.json",
    "spell":     "5e-SRD-Spells.json",
    "condition": "5e-SRD-Conditions.json",
    "rule":      "5e-SRD-Rules.json",
    "item":      "5e-SRD-Equipment.json",
}


def _fetch_json(url: str) -> list[dict]:
    import urllib.request
    print(f"  downloading {url} …", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def _load_local(path: Path, filename: str) -> list[dict]:
    full = path / filename
    if not full.exists():
        print(f"  not found: {full} — skipping", file=sys.stderr)
        return []
    with open(full) as f:
        return json.load(f)


def _items_for(data: list[dict] | dict) -> list[dict]:
    """Handle both list and dict-of-items formats."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # some versions use {index: item} dict
        return list(data.values())
    return []


def _chunk_rows(kind: str, edition: str, items: list[dict]) -> list[tuple]:
    """Convert raw SRD items to (edition, kind, name, name_norm, body, meta_json) tuples."""
    rows = []
    for item in items:
        name = item.get("name") or item.get("index") or ""
        if not name:
            continue
        nn = normalize_name(name)
        meta_json: str | None = None

        try:
            if kind == "monster":
                body = format_monster_body(item)
                meta = extract_monster_meta(item)
                meta_json = json.dumps(meta)
            elif kind == "spell":
                body = format_spell_body(item)
            elif kind == "condition":
                body = format_condition_body(item)
            elif kind == "rule":
                body = format_rule_body(item)
            elif kind == "item":
                body = format_equipment_body(item)
            else:
                body = json.dumps(item)
        except Exception as e:
            print(f"  warning: failed to format {name}: {e}", file=sys.stderr)
            body = name

        if not body.strip():
            body = name
        rows.append((edition, kind, name, nn, body, meta_json))
    return rows


def _insert_batch(conn, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO srd_chunks (edition, kind, name, name_norm, body, meta) "
            "VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
            rows,
        )
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest SRD into srd_chunks.")
    parser.add_argument("--edition", choices=["2014", "2024"], default="2014")
    parser.add_argument("--from", dest="src_dir", default=None,
                        help="Local directory with JSON files (skip network download).")
    parser.add_argument("--wipe", action="store_true",
                        help="Delete existing rows for this edition before inserting.")
    parser.add_argument("--kinds", nargs="+",
                        choices=["monster", "spell", "condition", "rule", "item"],
                        default=["monster", "spell", "condition", "rule", "item"],
                        help="Kinds to ingest (default: all).")
    args = parser.parse_args()

    dsn = os.environ.get("SUPABASE_URL")
    if not dsn:
        print("SUPABASE_URL not set.", file=sys.stderr)
        return 1

    src_path = Path(args.src_dir) if args.src_dir else None

    with psycopg.connect(dsn, autocommit=False) as conn:
        if args.wipe:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM srd_chunks WHERE edition=%s", (args.edition,))
            print(f"Wiped existing {args.edition} chunks.", file=sys.stderr)

        total = 0
        for kind in args.kinds:
            print(f"\nIngesting {kind}s …", file=sys.stderr)
            if src_path:
                data = _load_local(src_path, _LOCAL_NAMES[kind])
            else:
                url = _SOURCES.get(args.edition, {}).get(kind)
                if not url:
                    print(f"  No network source for {args.edition} {kind} — provide --from <local dir>", file=sys.stderr)
                    continue
                try:
                    data = _fetch_json(url)
                except Exception as e:
                    print(f"  download failed: {e}", file=sys.stderr)
                    continue

            items = _items_for(data)
            rows = _chunk_rows(kind, args.edition, items)
            n = _insert_batch(conn, rows)
            print(f"  inserted {n} {kind} rows", file=sys.stderr)
            total += n

        conn.commit()

    print(f"\nDone. Total rows inserted: {total}", file=sys.stderr)
    print(f"\nAttribution: Content from the D&D 5.1 System Reference Document, "
          f"Wizards of the Coast, CC-BY-4.0.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
