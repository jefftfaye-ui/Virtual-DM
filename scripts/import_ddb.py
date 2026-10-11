"""Local-first DDB character import — PRIMARY path per SPEC §3.

Datacenter IPs are often blocked by DDB bot protection. Run from a laptop.

Usage:
    python scripts/import_ddb.py <ddb_url_or_id> <player_name> [options]

Options:
    --campaign-id UUID    Campaign to import into (default: $DEFAULT_CAMPAIGN_ID)
    --reset-live-state    Reset HP, slots, conditions to fresh-import state
    --dry-run             Derive and print diff without writing to DB

Requires: SUPABASE_URL, DEFAULT_CAMPAIGN_ID (or --campaign-id)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Import DDB character into dm-server.")
    parser.add_argument("url_or_id", help="DDB character URL or numeric ID")
    parser.add_argument("player_name", help="Player's name (e.g. Jeff)")
    parser.add_argument("--campaign-id", default=None)
    parser.add_argument("--reset-live-state", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    campaign_id = args.campaign_id or os.environ.get("DEFAULT_CAMPAIGN_ID")
    if not campaign_id:
        print("Error: --campaign-id or DEFAULT_CAMPAIGN_ID required.", file=sys.stderr)
        return 1

    from ddb.client import extract_id, fetch_character, DDBError

    try:
        char_id = extract_id(args.url_or_id)
    except DDBError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Fetching DDB character {char_id}…", file=sys.stderr)
    try:
        snapshot = await fetch_character(char_id)
    except DDBError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from ddb.derive import derive, diff

    derived = derive(snapshot)
    print(f"\nDerived for: {derived['name']} ({derived['class_summary']}, level {derived['level']})", file=sys.stderr)
    print(f"  Source: {derived.get('_source')}", file=sys.stderr)
    print(f"  Max HP: {derived['max_hp']}, Speed: {derived['speed']}", file=sys.stderr)
    print(f"  AC: NOT DERIVED — set via update_character(overrides={{ac: N}})", file=sys.stderr)
    if "_charactercheck_error" in derived:
        print(f"  charactercheck warning: {derived['_charactercheck_error']}", file=sys.stderr)

    if args.dry_run:
        print("\n[dry-run] Would write:", file=sys.stderr)
        print(json.dumps({k: v for k, v in derived.items() if not k.startswith("_")}, indent=2))
        return 0

    from db import repo
    from ddb.importer import import_character

    async with repo.tx() as conn:
        result = await import_character(
            conn, campaign_id, snapshot, args.player_name,
            session_id=None,
            reset_live_state=args.reset_live_state,
        )

    print(f"\nImported: {result['name']}", file=sys.stderr)
    print(f"  character_id: {result['character_id']}", file=sys.stderr)
    print(f"  HP: {result['hp']}/{result['max_hp']}", file=sys.stderr)
    if result.get("mismatches"):
        print("\nMismatches (derived vs existing):", file=sys.stderr)
        for field, vals in result["mismatches"].items():
            print(f"  {field}: derived={vals['derived']} existing={vals['existing']}", file=sys.stderr)
        print("  → Fix mismatches with update_character(overrides={field: value})", file=sys.stderr)
    if result.get("overrides_applied"):
        print(f"\nOverrides preserved: {', '.join(result['overrides_applied'])}", file=sys.stderr)

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
