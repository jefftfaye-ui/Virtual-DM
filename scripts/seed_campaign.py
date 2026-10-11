"""Create a starter campaign and seed initial world lore.

Usage:
    python scripts/seed_campaign.py [--name "Campaign Name"] [--edition 2014|2024]

After running:
    1. Copy the DEFAULT_CAMPAIGN_ID printed below into your .env
    2. Import characters: python scripts/import_ddb.py <url> <player_name>
    3. Apply SPEC §8 changes to your claude.ai DM Project instructions

Requires: SUPABASE_URL
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


STARTER_LORE = [
    {
        "title": "Campaign Premise",
        "body": "A two-player D&D campaign with an AI Dungeon Master. "
                "Jeff and Julee explore a world of adventure together.",
        "dm_only": False,
    },
    {
        "title": "Lines and Veils",
        "body": "[FILL IN: List content that is off-limits (lines) and content "
                "that can occur but off-screen (veils). This lives in lore, not Project instructions, "
                "so it travels with the campaign state.]",
        "dm_only": True,
    },
    {
        "title": "House Rules",
        "body": "[FILL IN: Any house rules for this campaign — flanking, crit tables, etc.]",
        "dm_only": False,
    },
]


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="Stormwreck Isle")
    parser.add_argument("--edition", choices=["2014", "2024"], default="2014")
    parser.add_argument("--massive-damage", action="store_true", default=True)
    parser.add_argument("--hp-mode", choices=["average", "rolled"], default="average")
    args = parser.parse_args()

    dsn = os.environ.get("SUPABASE_URL")
    if not dsn:
        print("SUPABASE_URL not set.", file=sys.stderr)
        return 1

    from db import repo

    async with repo.tx() as conn:
        settings = {"monster_hp_mode": args.hp_mode, "massive_damage": args.massive_damage}
        row = await repo.fetchone(
            conn,
            "INSERT INTO campaigns (name, edition, settings) VALUES (%s,%s,%s::jsonb) RETURNING id",
            (args.name, args.edition, json.dumps(settings)),
        )
        campaign_id = str(row["id"])

        for lore in STARTER_LORE:
            await repo.execute(
                conn,
                "INSERT INTO lore (campaign_id, title, body, tags, dm_only) VALUES (%s,%s,%s,'{}', %s)",
                (campaign_id, lore["title"], lore["body"], lore["dm_only"]),
            )

    print(f"\nCampaign created: {args.name} ({args.edition})")
    print(f"DEFAULT_CAMPAIGN_ID={campaign_id}")
    print(f"\nNext steps:")
    print(f"  1. Add to .env: DEFAULT_CAMPAIGN_ID={campaign_id}")
    print(f"  2. Import Jeff's character:")
    print(f"     python scripts/import_ddb.py <ddb_url> Jeff --campaign-id {campaign_id}")
    print(f"  3. Import Julee's character:")
    print(f"     python scripts/import_ddb.py <ddb_url> Julee --campaign-id {campaign_id}")
    print(f"  4. Run: python scripts/ingest_srd.py --edition {args.edition}")
    print(f"  5. Edit the Lines/Veils lore entry in your DB")
    print(f"  6. Apply SPEC §8 changes to claude.ai DM Project instructions")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
