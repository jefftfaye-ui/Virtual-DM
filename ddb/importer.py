"""DB operations for DDB import. Used by both the CLI script and the MCP tool.

Handles upsert logic, HP ratio preservation, overrides merge.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from typing import Any

from db import repo
from ddb.derive import derive, diff
from tools._util import write_event


async def _upsert_character(conn, campaign_id: str, derived: dict,
                             existing: dict | None, reset_live_state: bool) -> dict:
    """Write derived fields to the characters table.

    - overrides always win over derived values
    - inventory edits preserved unless reset_live_state
    - HP preserved by ratio unless reset_live_state or character was dead
    """
    ovr = dict((existing or {}).get("overrides") or {})

    # Apply overrides: any key in overrides wins over derived
    def resolve(key: str, default: Any = None) -> Any:
        if key in ovr:
            return ovr[key]
        return derived.get(key, default)

    max_hp = resolve("max_hp", derived.get("max_hp", 1))

    # HP ratio preservation
    if existing and not reset_live_state and not existing.get("dead"):
        old_max = existing.get("max_hp") or max_hp
        old_hp = existing.get("hp") or max_hp
        ratio = old_hp / old_max if old_max else 1.0
        hp = max(1, math.floor(ratio * max_hp))
    elif existing and not reset_live_state and existing.get("dead"):
        hp = 0  # keep dead
    else:
        hp = max_hp  # full HP on reset or fresh import

    # Inventory: keep existing edits unless reset
    if existing and not reset_live_state:
        inventory = existing.get("inventory") or []
    else:
        inventory = []

    # Slots: fresh on import (live state)
    spell_slots = resolve("spell_slots", derived.get("spell_slots") or {})
    # Ensure used=0 on fresh import; preserve used on re-import if not reset
    if existing and not reset_live_state:
        old_slots = existing.get("spell_slots") or {}
        for lvl, slot in spell_slots.items():
            if lvl in old_slots:
                slot["used"] = old_slots[lvl].get("used", 0)

    pact_slots = resolve("pact_slots", derived.get("pact_slots"))
    if pact_slots and existing and not reset_live_state:
        old_pact = existing.get("pact_slots") or {}
        pact_slots = {**pact_slots, "used": old_pact.get("used", 0)}

    hit_dice = resolve("hit_dice", derived.get("hit_dice") or {})
    if existing and not reset_live_state:
        old_hd = existing.get("hit_dice") or {}
        for die, pool in hit_dice.items():
            if die in old_hd:
                pool["used"] = old_hd[die].get("used", 0)

    resources = (existing or {}).get("resources") or {}
    death_saves = (existing or {}).get("death_saves") or {"successes": 0, "failures": 0}
    conditions = (existing or {}).get("conditions") or []
    exhaustion = (existing or {}).get("exhaustion") or 0
    inspiration = (existing or {}).get("inspiration") or False
    temp_hp = 0 if reset_live_state else (existing or {}).get("temp_hp", 0)
    stable = False if reset_live_state else (existing or {}).get("stable", False)
    dead = False if reset_live_state else (existing or {}).get("dead", False)

    abilities = resolve("abilities", derived.get("abilities") or {})
    saves = resolve("saves", derived.get("saves") or {})
    skills = resolve("skills", derived.get("skills") or {})
    speed = resolve("speed", derived.get("speed") or 30)
    level = resolve("level", derived.get("level", 1))
    class_summary = resolve("class_summary", derived.get("class_summary", ""))
    name = derived.get("name") or (existing or {}).get("name") or "Unknown"
    ddb_id = derived.get("ddb_id") or ""
    gold = (existing.get("gold") or 0) if (existing and not reset_live_state) else derived.get("gold", 0)

    if existing:
        await repo.execute(
            conn,
            """
            UPDATE characters SET
                name=%s, ddb_id=%s, ddb_snapshot=%s::jsonb, ddb_synced_at=now(),
                level=%s, class_summary=%s,
                max_hp=%s, hp=%s, temp_hp=%s, speed=%s,
                abilities=%s::jsonb, saves=%s::jsonb, skills=%s::jsonb,
                spell_slots=%s::jsonb, pact_slots=%s::jsonb, hit_dice=%s::jsonb,
                resources=%s::jsonb, conditions=%s, death_saves=%s::jsonb,
                stable=%s, dead=%s, exhaustion=%s, inspiration=%s,
                inventory=%s::jsonb, gold=%s, overrides=%s::jsonb
            WHERE id=%s
            """,
            (
                name, ddb_id, json.dumps({"imported": True}), level, class_summary,
                max_hp, hp, temp_hp, speed,
                json.dumps(abilities), json.dumps(saves), json.dumps(skills),
                json.dumps(spell_slots), json.dumps(pact_slots), json.dumps(hit_dice),
                json.dumps(resources), conditions, json.dumps(death_saves),
                stable, dead, exhaustion, inspiration,
                json.dumps(inventory), gold, json.dumps(ovr),
                existing["id"],
            ),
        )
        char_id = str(existing["id"])
    else:
        row = await repo.fetchone(
            conn,
            """
            INSERT INTO characters (
                campaign_id, player_name, name, ddb_id, ddb_snapshot, ddb_synced_at,
                level, class_summary, max_hp, hp, temp_hp, speed,
                abilities, saves, skills, spell_slots, pact_slots, hit_dice,
                resources, conditions, death_saves, stable, dead, exhaustion,
                inspiration, inventory, gold, overrides, resistances, immunities, vulnerabilities
            ) VALUES (
                %s, %s, %s, %s, %s::jsonb, now(),
                %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                %s::jsonb, %s, %s::jsonb, %s, %s, %s,
                %s, %s::jsonb, %s, %s::jsonb, '{}', '{}', '{}'
            ) RETURNING id
            """,
            (
                campaign_id, derived.get("_player_name", "Player"), name,
                ddb_id, json.dumps({"imported": True}),
                level, class_summary, max_hp, hp, temp_hp, speed,
                json.dumps(abilities), json.dumps(saves), json.dumps(skills),
                json.dumps(spell_slots), json.dumps(pact_slots), json.dumps(hit_dice),
                json.dumps(resources), conditions, json.dumps(death_saves),
                stable, dead, exhaustion,
                inspiration, json.dumps(inventory), gold, json.dumps(ovr),
            ),
        )
        char_id = str(row["id"])

    return {"character_id": char_id, "name": name, "hp": hp, "max_hp": max_hp}


async def import_character(
    conn,
    campaign_id: str,
    snapshot: dict,
    player_name: str,
    session_id: str | None,
    *,
    reset_live_state: bool = False,
) -> dict:
    """Full import: derive → merge existing → upsert → event log.

    Returns {character_id, name, hp, max_hp, mismatches, overrides_applied}.
    """
    derived = derive(snapshot)
    derived["_player_name"] = player_name

    ddb_id = derived.get("ddb_id") or ""
    existing = None
    if ddb_id:
        existing = await repo.fetchone(
            conn,
            "SELECT * FROM characters WHERE campaign_id=%s AND ddb_id=%s",
            (campaign_id, ddb_id),
        )

    mismatches = diff(derived, dict(existing) if existing else {}) if existing else {}
    ovr_applied = list((existing or {}).get("overrides", {}).keys()) if existing else []

    result = await _upsert_character(conn, campaign_id, derived, existing, reset_live_state)

    await write_event(
        conn, campaign_id, "ddb_import",
        {
            "character_id": result["character_id"],
            "ddb_id": ddb_id,
            "player_name": player_name,
            "source": derived.get("_source"),
            "mismatches": mismatches,
            "overrides_applied": ovr_applied,
            "reset_live_state": reset_live_state,
        },
        f"DDB import for {derived.get('name')}",
        session_id=session_id,
    )

    return {
        **result,
        "mismatches": mismatches,
        "overrides_applied": ovr_applied,
        "derivation_source": derived.get("_source"),
        "note": (
            "AC not derived — set via update_character(overrides={'ac': N}). "
            + (f"charactercheck error: {derived['_charactercheck_error']}" if "_charactercheck_error" in derived else "")
        ),
    }
