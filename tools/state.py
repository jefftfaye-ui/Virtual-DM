"""State tools: get_state, update_character, death_save, rest, set_scene, undo_last_event.

Each tool has a public function (opens its own repo.tx()) and an _impl(conn, ...) that
tests and other tools can call within an existing transaction.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from db import repo
from rules import damage as dmg_rules
from rules import death as death_rules
from rules import rest as rest_rules
from rules import exhaustion as exhaust_rules
from tools._util import (
    resolve_campaign_id,
    to_str,
    write_event,
    get_campaign,
    get_active_session_id,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _char_to_target(c: dict) -> dmg_rules.TargetState:
    return dmg_rules.TargetState(
        hp=c["hp"],
        max_hp=c["max_hp"],
        temp_hp=c["temp_hp"],
        resistances=list(c.get("resistances") or []),
        immunities=list(c.get("immunities") or []),
        vulnerabilities=list(c.get("vulnerabilities") or []),
        concentrating=bool(c.get("concentrating_on")),
        stable=bool(c.get("stable")),
        dead=bool(c.get("dead")),
        death_successes=(c.get("death_saves") or {}).get("successes", 0),
        death_failures=(c.get("death_saves") or {}).get("failures", 0),
    )


def _pc_summary(c: dict) -> dict:
    return {
        "id": str(c["id"]),
        "name": c["name"],
        "player_name": c["player_name"],
        "class_summary": c.get("class_summary"),
        "level": c["level"],
        "ac": c.get("ac"),
        "hp": c["hp"],
        "max_hp": c["max_hp"],
        "temp_hp": c["temp_hp"],
        "conditions": list(c.get("conditions") or []),
        "concentrating_on": c.get("concentrating_on"),
        "death_saves": c.get("death_saves") or {"successes": 0, "failures": 0},
        "stable": bool(c.get("stable")),
        "dead": bool(c.get("dead")),
        "spell_slots": c.get("spell_slots") or {},
        "pact_slots": c.get("pact_slots"),
        "hit_dice": c.get("hit_dice") or {},
        "inspiration": bool(c.get("inspiration")),
        "exhaustion": c.get("exhaustion", 0),
        "gold": c.get("gold", 0),
        "inventory": list(c.get("inventory") or []),
    }


def _clock_summary(cl: dict) -> dict:
    out = {
        "id": str(cl["id"]),
        "name": cl["name"],
        "filled": cl["filled"],
        "segments": cl["segments"],
    }
    if cl.get("visible", True):
        out["visible"] = True
    # hidden clocks omit consequence here; revealed only when filled via tick_clock
    return out


# ─── P2.2: get_state ──────────────────────────────────────────────────────────

async def _get_state_impl(
    conn,
    campaign_id: str,
    include: list[str],
) -> dict:
    campaign = await repo.fetchone(
        conn, "SELECT * FROM campaigns WHERE id = %s", (campaign_id,)
    )
    if not campaign:
        return {"error": "campaign not found", "hint": f"id={campaign_id}"}

    result: dict[str, Any] = {}

    if "party" in include:
        chars = await repo.fetchall(
            conn,
            "SELECT * FROM characters WHERE campaign_id = %s ORDER BY player_name",
            (campaign_id,),
        )
        result["party"] = [_pc_summary(c) for c in chars]

    if "scene" in include:
        scene: dict = {
            "description": campaign.get("current_scene"),
            "in_game_date": campaign.get("in_game_date"),
        }
        loc_id = campaign.get("current_location_id")
        if loc_id:
            loc = await repo.fetchone(
                conn, "SELECT id, name, description FROM locations WHERE id = %s", (loc_id,)
            )
            if loc:
                scene["location"] = loc["name"]
                scene["location_description"] = loc.get("description")
                # NPCs at this location
                npcs = await repo.fetchall(
                    conn,
                    "SELECT name, role, disposition, public_description, status FROM npcs "
                    "WHERE location_id = %s AND campaign_id = %s AND status = 'alive' ORDER BY name",
                    (loc_id, campaign_id),
                )
                scene["npcs_present"] = [
                    {"name": n["name"], "role": n.get("role"), "disposition": n["disposition"],
                     "description": n.get("public_description")}
                    for n in npcs
                ]
            else:
                scene["location"] = None
        result["scene"] = scene

    if "encounter" in include:
        enc = await repo.fetchone(
            conn,
            "SELECT * FROM encounters WHERE campaign_id = %s AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (campaign_id,),
        )
        if enc:
            combatants = await repo.fetchall(
                conn,
                "SELECT id, name, kind, hp, max_hp, status, initiative, conditions FROM combatants "
                "WHERE encounter_id = %s ORDER BY initiative DESC NULLS LAST, dex_mod DESC, tiebreak DESC",
                (enc["id"],),
            )
            result["encounter"] = {
                "id": str(enc["id"]),
                "name": enc["name"],
                "round": enc["round"],
                "turn_index": enc["turn_index"],
                "combatants": [
                    {
                        "id": str(c["id"]),
                        "name": c["name"],
                        "kind": c["kind"],
                        "hp": c["hp"],
                        "max_hp": c["max_hp"],
                        "status": c["status"],
                        "initiative": c["initiative"],
                        "conditions": list(c.get("conditions") or []),
                    }
                    for c in combatants
                ],
            }
        else:
            result["encounter"] = None

    if "quests" in include:
        quests = await repo.fetchall(
            conn,
            "SELECT title, status, summary FROM quests WHERE campaign_id = %s ORDER BY created_at",
            (campaign_id,),
        )
        result["quests"] = [dict(q) for q in quests]

    if "clocks" in include:
        clocks = await repo.fetchall(
            conn,
            "SELECT * FROM clocks WHERE campaign_id = %s ORDER BY created_at",
            (campaign_id,),
        )
        result["clocks"] = [_clock_summary(cl) for cl in clocks]

    return result


async def get_state(
    include: list[str] | None = None,
    campaign_id: str | None = None,
) -> dict:
    """Snapshot party state. include: party, scene, encounter, quests, clocks.
    Excludes secrets, dm_only lore, NPC knows, hidden clock consequences."""
    cid = resolve_campaign_id(campaign_id)
    inc = include or ["party", "scene", "encounter", "quests", "clocks"]
    async with repo.tx() as conn:
        return await _get_state_impl(conn, cid, inc)


# ─── P2.3: update_character ───────────────────────────────────────────────────

def _apply_conditions(current: list[str], add: list[str] | None, remove: list[str] | None) -> list[str]:
    s = {c.lower().strip() for c in current}
    for c in (add or []):
        s.add(c.lower().strip())
    for c in (remove or []):
        s.discard(c.lower().strip())
    return sorted(s)


def _slot_use(slots: dict, level: str, restore: bool) -> dict | str:
    """Return error string or updated slots dict."""
    key = str(level)
    if key not in slots:
        return f"no spell slot level {level}"
    slot = slots[key]
    if restore:
        slots[key] = {**slot, "used": max(0, slot["used"] - 1)}
    else:
        if slot["used"] >= slot["max"]:
            return f"no level-{level} slots remaining (used={slot['used']}/{slot['max']})"
        slots[key] = {**slot, "used": slot["used"] + 1}
    return slots


def _pact_use(pact: dict | None, restore: bool) -> dict | str:
    if not pact:
        return "character has no Pact Magic slots"
    if restore:
        return {**pact, "used": max(0, pact["used"] - 1)}
    if pact["used"] >= pact["max"]:
        return f"no pact slots remaining (used={pact['used']}/{pact['max']})"
    return {**pact, "used": pact["used"] + 1}


def _resource_use(resources: dict, name: str, restore: bool) -> dict | str:
    if name not in resources:
        return f"unknown resource '{name}'"
    res = resources[name]
    if restore:
        resources[name] = {**res, "used": max(0, res["used"] - 1)}
    else:
        if res["used"] >= res["max"]:
            return f"resource '{name}' exhausted (used={res['used']}/{res['max']})"
        resources[name] = {**res, "used": res["used"] + 1}
    return resources


def _hit_die_spend(hit_dice: dict, die_key: str, count: int) -> dict | str:
    if die_key not in hit_dice:
        return f"no hit die '{die_key}'"
    pool = hit_dice[die_key]
    available = pool["max"] - pool["used"]
    if count > available:
        return f"only {available} {die_key} hit dice available"
    hit_dice[die_key] = {**pool, "used": pool["used"] + count}
    return hit_dice


async def _update_character_impl(
    conn,
    character_id: str,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
    *,
    edition: str = "2014",
    massive_damage_enabled: bool = True,
    damage: dict | None = None,
    heal: int = 0,
    set_hp: int | None = None,
    temp_hp: int | None = None,
    add_conditions: list[str] | None = None,
    remove_conditions: list[str] | None = None,
    use_slot: int | None = None,
    restore_slot: int | None = None,
    use_pact_slot: bool = False,
    restore_pact_slot: bool = False,
    use_resource: str | None = None,
    restore_resource: str | None = None,
    spend_hit_dice: dict | None = None,  # {"die": "d8", "count": 1}
    start_concentration: str | None = None,
    end_concentration: bool = False,
    inspiration: bool | None = None,
    inventory_add: list[dict] | None = None,
    inventory_remove: str | None = None,
    gold_delta: int = 0,
    exhaustion_delta: int = 0,
    overrides: dict | None = None,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    char = await repo.fetchone(
        conn, "SELECT * FROM characters WHERE id = %s FOR UPDATE", (character_id,)
    )
    if not char:
        return {"error": "character not found", "hint": f"id={character_id}"}

    # Snapshot for undo and for response diff
    prev = {
        "hp": char["hp"], "temp_hp": char["temp_hp"], "max_hp": char["max_hp"],
        "conditions": list(char.get("conditions") or []),
        "concentrating_on": char.get("concentrating_on"),
        "death_saves": dict(char.get("death_saves") or {"successes": 0, "failures": 0}),
        "stable": char.get("stable"), "dead": char.get("dead"),
        "spell_slots": deepcopy(char.get("spell_slots") or {}),
        "pact_slots": deepcopy(char.get("pact_slots")),
        "resources": deepcopy(char.get("resources") or {}),
        "hit_dice": deepcopy(char.get("hit_dice") or {}),
        "inspiration": char.get("inspiration"),
        "inventory": deepcopy(char.get("inventory") or []),
        "gold": char.get("gold", 0),
        "exhaustion": char.get("exhaustion", 0),
        "overrides": deepcopy(char.get("overrides") or {}),
    }

    # Working copies
    hp = char["hp"]
    max_hp = char["max_hp"]
    temp_hp_val = char["temp_hp"]
    conditions = list(char.get("conditions") or [])
    concentrating_on = char.get("concentrating_on")
    death_saves = dict(char.get("death_saves") or {"successes": 0, "failures": 0})
    stable = bool(char.get("stable"))
    dead = bool(char.get("dead"))
    spell_slots = deepcopy(char.get("spell_slots") or {})
    pact_slots = deepcopy(char.get("pact_slots"))
    resources = deepcopy(char.get("resources") or {})
    hit_dice = deepcopy(char.get("hit_dice") or {})
    insp = char.get("inspiration", False)
    inventory = deepcopy(char.get("inventory") or [])
    gold = char.get("gold", 0)
    exhaustion = char.get("exhaustion", 0)
    ovr = deepcopy(char.get("overrides") or {})

    response: dict[str, Any] = {}

    # 1. Damage
    if damage is not None:
        target = _char_to_target({
            **char, "hp": hp, "temp_hp": temp_hp_val,
            "concentrating_on": concentrating_on, "stable": stable, "dead": dead,
            "death_saves": death_saves,
        })
        out = dmg_rules.apply_damage(
            target,
            dmg_rules.DamageInput(
                amount=damage["amount"],
                type=damage.get("type", "untyped"),
                crit=damage.get("crit", False),
            ),
            edition=edition,
            massive_damage_enabled=massive_damage_enabled,
        )
        hp = out.hp_after
        temp_hp_val = out.temp_hp_after
        if out.ended_concentration:
            concentrating_on = None
        if out.dead:
            dead = True
        if out.dropped:
            response["dropped"] = True
        if out.death_failures_added:
            f = min(3, death_saves["failures"] + out.death_failures_added)
            death_saves["failures"] = f
            if f >= 3:
                dead = True
                response["dead"] = True
        if out.concentration_check:
            response["concentration_check"] = out.concentration_check
        response.update({
            "resisted": out.resisted,
            "immune": out.immune,
            "vulnerable": out.vulnerable,
            "temp_absorbed": out.temp_absorbed,
        })

    # 2. Heal
    if heal and heal > 0:
        target = _char_to_target({
            **char, "hp": hp, "temp_hp": temp_hp_val,
            "concentrating_on": concentrating_on, "stable": stable, "dead": dead,
            "death_saves": death_saves,
        })
        dmg_rules.apply_heal(target, heal)
        hp = target.hp
        if target.hp > 0:
            death_saves = {"successes": 0, "failures": 0}
            stable = False

    # 3. set_hp / temp_hp overrides
    if set_hp is not None:
        hp = max(0, min(max_hp, set_hp))
    if temp_hp is not None:
        temp_hp_val = max(0, temp_hp)

    # 4. Conditions
    if add_conditions or remove_conditions:
        conditions = _apply_conditions(conditions, add_conditions, remove_conditions)

    # 5. Spell slots
    if use_slot is not None:
        result = _slot_use(spell_slots, use_slot, restore=False)
        if isinstance(result, str):
            return {"error": result, "hint": "cannot overspend slots"}
        spell_slots = result

    if restore_slot is not None:
        result = _slot_use(spell_slots, restore_slot, restore=True)
        if isinstance(result, str):
            return {"error": result, "hint": ""}
        spell_slots = result

    # 6. Pact slots
    if use_pact_slot:
        result = _pact_use(pact_slots, restore=False)
        if isinstance(result, str):
            return {"error": result, "hint": "cannot overspend pact slots"}
        pact_slots = result

    if restore_pact_slot:
        result = _pact_use(pact_slots, restore=True)
        if isinstance(result, str):
            return {"error": result, "hint": ""}
        pact_slots = result

    # 7. Resources
    if use_resource is not None:
        result = _resource_use(resources, use_resource, restore=False)
        if isinstance(result, str):
            return {"error": result, "hint": "cannot overspend resources"}
        resources = result

    if restore_resource is not None:
        result = _resource_use(resources, restore_resource, restore=True)
        if isinstance(result, str):
            return {"error": result, "hint": ""}
        resources = result

    # 8. Hit dice
    if spend_hit_dice is not None:
        result = _hit_die_spend(hit_dice, spend_hit_dice["die"], spend_hit_dice.get("count", 1))
        if isinstance(result, str):
            return {"error": result, "hint": "cannot overspend hit dice"}
        hit_dice = result

    # 9. Concentration
    if start_concentration is not None:
        concentrating_on = start_concentration
    if end_concentration:
        concentrating_on = None

    # 10. Misc
    if inspiration is not None:
        insp = inspiration

    if inventory_add:
        for item in inventory_add:
            inventory.append(item)

    if inventory_remove:
        inventory = [i for i in inventory if i.get("item") != inventory_remove]

    if gold_delta:
        gold = max(0, gold + gold_delta)

    if exhaustion_delta:
        exhaustion = max(0, exhaustion + exhaustion_delta)
        response["exhaustion"] = {
            "level": exhaustion,
            "effect": exhaust_rules.describe(exhaustion, edition=edition),
        }

    if overrides:
        ovr.update(overrides)

    # Persist
    await repo.execute(
        conn,
        """
        UPDATE characters SET
            hp=%s, temp_hp=%s, conditions=%s, concentrating_on=%s,
            death_saves=%s::jsonb, stable=%s, dead=%s,
            spell_slots=%s::jsonb, pact_slots=%s::jsonb, resources=%s::jsonb,
            hit_dice=%s::jsonb, inspiration=%s, inventory=%s::jsonb, gold=%s,
            exhaustion=%s, overrides=%s::jsonb
        WHERE id=%s
        """,
        (
            hp, temp_hp_val, conditions, concentrating_on,
            json.dumps(death_saves), stable, dead,
            json.dumps(spell_slots), json.dumps(pact_slots), json.dumps(resources),
            json.dumps(hit_dice), insp, json.dumps(inventory), gold,
            exhaustion, json.dumps(ovr),
            character_id,
        ),
    )

    event_payload = {
        "character_id": character_id,
        "prev": prev,
        "next": {
            "hp": hp, "temp_hp": temp_hp_val, "conditions": conditions,
            "concentrating_on": concentrating_on, "death_saves": death_saves,
            "stable": stable, "dead": dead,
        },
    }
    if damage:
        event_payload["damage"] = damage
    if heal:
        event_payload["heal"] = heal

    await write_event(conn, campaign_id, "update_character", event_payload, reason, session_id=session_id)

    result_out = {
        "character_id": character_id,
        "hp_after": hp,
        "temp_hp_after": temp_hp_val,
        "conditions": conditions,
        "concentrating_on": concentrating_on,
        "death_saves": death_saves,
        "stable": stable,
        "dead": dead,
        **response,
    }
    await repo.store_idempotent(conn, campaign_id, request_id, to_str(result_out))
    return to_str(result_out)


async def update_character(  # noqa: PLR0913
    character_id: str,
    reason: str,
    campaign_id: str | None = None,
    request_id: str | None = None,
    damage: dict | None = None,
    heal: int = 0,
    set_hp: int | None = None,
    temp_hp: int | None = None,
    add_conditions: list[str] | None = None,
    remove_conditions: list[str] | None = None,
    use_slot: int | None = None,
    restore_slot: int | None = None,
    use_pact_slot: bool = False,
    restore_pact_slot: bool = False,
    use_resource: str | None = None,
    restore_resource: str | None = None,
    spend_hit_dice: dict | None = None,
    start_concentration: str | None = None,
    end_concentration: bool = False,
    inspiration: bool | None = None,
    inventory_add: list[dict] | None = None,
    inventory_remove: str | None = None,
    gold_delta: int = 0,
    exhaustion_delta: int = 0,
    overrides: dict | None = None,
) -> dict:
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        campaign = await get_campaign(conn, cid)
        if not campaign:
            return {"error": "campaign not found"}
        edition = str(campaign.get("edition", "2014"))
        massive = (campaign.get("settings") or {}).get("massive_damage", True)
        session_id = await get_active_session_id(conn, cid)
        return await _update_character_impl(
            conn, character_id, reason, cid, session_id, request_id,
            edition=edition, massive_damage_enabled=massive,
            damage=damage, heal=heal, set_hp=set_hp, temp_hp=temp_hp,
            add_conditions=add_conditions, remove_conditions=remove_conditions,
            use_slot=use_slot, restore_slot=restore_slot,
            use_pact_slot=use_pact_slot, restore_pact_slot=restore_pact_slot,
            use_resource=use_resource, restore_resource=restore_resource,
            spend_hit_dice=spend_hit_dice,
            start_concentration=start_concentration, end_concentration=end_concentration,
            inspiration=inspiration,
            inventory_add=inventory_add, inventory_remove=inventory_remove,
            gold_delta=gold_delta, exhaustion_delta=exhaustion_delta,
            overrides=overrides,
        )


# ─── P2.4: death_save ─────────────────────────────────────────────────────────

async def _death_save_impl(
    conn, character_id: str, campaign_id: str, session_id: str | None, request_id: str | None
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    char = await repo.fetchone(
        conn, "SELECT * FROM characters WHERE id = %s FOR UPDATE", (character_id,)
    )
    if not char:
        return {"error": "character not found"}
    if char["hp"] > 0:
        return {"error": "character is conscious — no death save needed", "hint": "hp > 0"}
    if char["stable"]:
        return {"error": "character is stable", "hint": "no death save needed until damaged"}
    if char["dead"]:
        return {"error": "character is dead"}

    from tools.dice import _roll_impl

    roll_result = await _roll_impl(
        conn, "1d20", "death saving throw", char["name"], campaign_id,
        session_id=session_id,
    )
    natural = roll_result["natural"]

    ds = dict(char.get("death_saves") or {"successes": 0, "failures": 0})
    outcome = death_rules.resolve(natural, successes=ds["successes"], failures=ds["failures"])

    new_hp = char["hp"]
    new_stable = char["stable"]
    new_dead = char["dead"]

    if outcome.regained_hp:
        new_hp = 1
        ds = {"successes": 0, "failures": 0}
    elif outcome.dead:
        new_dead = True
        ds["failures"] = outcome.failures
    elif outcome.stable:
        new_stable = True
        ds = {"successes": 0, "failures": 0}
    else:
        ds = {"successes": outcome.successes, "failures": outcome.failures}

    await repo.execute(
        conn,
        "UPDATE characters SET hp=%s, death_saves=%s::jsonb, stable=%s, dead=%s WHERE id=%s",
        (new_hp, json.dumps(ds), new_stable, new_dead, character_id),
    )

    await write_event(
        conn, campaign_id, "death_save",
        {
            "character_id": character_id,
            "natural": natural,
            "roll_id": roll_result["roll_id"],
            "prev_death_saves": dict(char.get("death_saves") or {}),
            "outcome": outcome.message,
        },
        f"death save for {char['name']}",
        session_id=session_id,
    )

    result_out = {
        "character_id": character_id,
        "roll_id": roll_result["roll_id"],
        "natural": natural,
        "successes": ds["successes"],
        "failures": ds["failures"],
        "stable": new_stable,
        "dead": new_dead,
        "hp_after": new_hp,
        "message": outcome.message,
    }
    await repo.store_idempotent(conn, campaign_id, request_id, result_out)
    return result_out


async def death_save(character_id: str, campaign_id: str | None = None, request_id: str | None = None) -> dict:
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _death_save_impl(conn, character_id, cid, session_id, request_id)


# ─── P2.5: rest ───────────────────────────────────────────────────────────────

async def _rest_impl(
    conn,
    kind: str,
    character_ids: list[str],
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
    edition: str,
) -> dict:
    if kind not in ("short", "long"):
        return {"error": f"kind must be 'short' or 'long', got {kind!r}"}

    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    if not character_ids:
        chars = await repo.fetchall(
            conn, "SELECT id FROM characters WHERE campaign_id = %s", (campaign_id,)
        )
        character_ids = [str(c["id"]) for c in chars]

    applied = []
    for cid_char in character_ids:
        char = await repo.fetchone(
            conn, "SELECT * FROM characters WHERE id = %s FOR UPDATE", (cid_char,)
        )
        if not char:
            applied.append({"character_id": cid_char, "error": "not found"})
            continue

        char_dict = dict(char)
        prev = {
            "hp": char_dict["hp"], "temp_hp": char_dict["temp_hp"],
            "spell_slots": deepcopy(char_dict.get("spell_slots") or {}),
            "pact_slots": deepcopy(char_dict.get("pact_slots")),
            "resources": deepcopy(char_dict.get("resources") or {}),
            "hit_dice": deepcopy(char_dict.get("hit_dice") or {}),
            "death_saves": dict(char_dict.get("death_saves") or {}),
            "stable": char_dict.get("stable"),
            "exhaustion": char_dict.get("exhaustion", 0),
        }

        if kind == "short":
            updated = rest_rules.short_rest(char_dict)
        else:
            updated = rest_rules.long_rest(char_dict, edition=edition)

        await repo.execute(
            conn,
            """
            UPDATE characters SET
                hp=%s, temp_hp=%s, spell_slots=%s::jsonb, pact_slots=%s::jsonb,
                resources=%s::jsonb, hit_dice=%s::jsonb, death_saves=%s::jsonb,
                stable=%s, exhaustion=%s
            WHERE id=%s
            """,
            (
                updated["hp"], updated["temp_hp"],
                json.dumps(updated.get("spell_slots") or {}),
                json.dumps(updated.get("pact_slots")),
                json.dumps(updated.get("resources") or {}),
                json.dumps(updated.get("hit_dice") or {}),
                json.dumps(updated.get("death_saves") or {"successes": 0, "failures": 0}),
                updated.get("stable", False),
                updated.get("exhaustion", 0),
                cid_char,
            ),
        )

        diff = {k: v for k, v in updated.items() if k in prev and prev[k] != v}
        await write_event(
            conn, campaign_id, f"{kind}_rest",
            {"character_id": cid_char, "prev": prev, "diff": diff},
            reason, session_id=session_id,
        )
        applied.append({"character_id": cid_char, "name": char_dict["name"], "diff": diff})

    result_out = {"kind": kind, "applied": applied}
    await repo.store_idempotent(conn, campaign_id, request_id, result_out)
    return result_out


async def rest(
    kind: str,
    character_ids: list[str] | None = None,
    reason: str = "rest",
    campaign_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        campaign = await get_campaign(conn, cid)
        if not campaign:
            return {"error": "campaign not found"}
        edition = str(campaign.get("edition", "2014"))
        session_id = await get_active_session_id(conn, cid)
        return await _rest_impl(
            conn, kind, character_ids or [], reason, cid, session_id, request_id, edition
        )


# ─── P2.6: set_scene ──────────────────────────────────────────────────────────

async def _set_scene_impl(
    conn,
    description: str,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    *,
    location_id: str | None = None,
    in_game_date: str | None = None,
) -> dict:
    prev_row = await repo.fetchone(
        conn,
        "SELECT current_scene, in_game_date, current_location_id FROM campaigns WHERE id=%s",
        (campaign_id,),
    )

    updates = ["current_scene = %s"]
    params: list[Any] = [description]

    if in_game_date is not None:
        updates.append("in_game_date = %s")
        params.append(in_game_date)

    if location_id is not None:
        updates.append("current_location_id = %s")
        params.append(location_id)

    params.append(campaign_id)
    await repo.execute(
        conn,
        f"UPDATE campaigns SET {', '.join(updates)} WHERE id = %s",
        tuple(params),
    )

    # get location name for response
    loc_name = None
    if location_id:
        loc = await repo.fetchone(conn, "SELECT name FROM locations WHERE id=%s", (location_id,))
        loc_name = loc["name"] if loc else None

    await write_event(
        conn, campaign_id, "set_scene",
        {
            "prev": to_str(dict(prev_row or {})),
            "description": description,
            "in_game_date": in_game_date,
            "location_id": location_id,
        },
        reason, session_id=session_id,
    )

    return {
        "description": description,
        "in_game_date": in_game_date,
        "location": loc_name,
    }


async def set_scene(
    description: str,
    reason: str,
    location_id: str | None = None,
    in_game_date: str | None = None,
    campaign_id: str | None = None,
) -> dict:
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _set_scene_impl(
            conn, description, reason, cid, session_id,
            location_id=location_id, in_game_date=in_game_date,
        )


# ─── P2.7: undo_last_event ────────────────────────────────────────────────────

_UNDOABLE_TYPES = {"update_character", "short_rest", "long_rest", "set_scene"}


async def _undo_last_event_impl(conn, reason: str, campaign_id: str, session_id: str | None) -> dict:
    # active session boundary
    if session_id:
        session = await repo.fetchone(
            conn, "SELECT started_at FROM sessions WHERE id=%s", (session_id,)
        )
        session_started = session["started_at"] if session else None
    else:
        session_started = None

    # find last undoable event in this campaign
    where = "campaign_id = %s AND compensates_event_id IS NULL AND type != 'undo'"
    params: list[Any] = [campaign_id]

    if session_started:
        where += " AND created_at >= %s"
        params.append(session_started)

    row = await repo.fetchone(
        conn,
        f"SELECT * FROM events WHERE {where} ORDER BY created_at DESC LIMIT 1",
        tuple(params),
    )

    if not row:
        return {"error": "nothing to undo in this session", "hint": "rolls cannot be undone"}

    event_type = row["type"]
    if event_type not in _UNDOABLE_TYPES:
        return {
            "error": f"cannot undo event of type '{event_type}'",
            "hint": "rolls cannot be undone",
        }

    payload = row["payload"] if isinstance(row["payload"], dict) else {}
    prev = payload.get("prev", {})

    if event_type == "update_character":
        char_id = payload.get("character_id")
        if char_id and prev:
            fields = list(prev.keys())
            set_clause = ", ".join(f"{f}=%s" for f in fields)
            values = []
            for f in fields:
                v = prev[f]
                if isinstance(v, (dict, list)):
                    values.append(json.dumps(v))
                else:
                    values.append(v)
            values.append(char_id)
            await repo.execute(
                conn,
                f"UPDATE characters SET {set_clause} WHERE id=%s",
                tuple(values),
            )

    elif event_type in ("short_rest", "long_rest"):
        char_id = payload.get("character_id")
        if char_id and prev:
            await repo.execute(
                conn,
                """
                UPDATE characters SET
                    hp=%s, temp_hp=%s, spell_slots=%s::jsonb, pact_slots=%s::jsonb,
                    resources=%s::jsonb, hit_dice=%s::jsonb, death_saves=%s::jsonb,
                    stable=%s, exhaustion=%s
                WHERE id=%s
                """,
                (
                    prev.get("hp"), prev.get("temp_hp"),
                    json.dumps(prev.get("spell_slots") or {}),
                    json.dumps(prev.get("pact_slots")),
                    json.dumps(prev.get("resources") or {}),
                    json.dumps(prev.get("hit_dice") or {}),
                    json.dumps(prev.get("death_saves") or {}),
                    prev.get("stable"), prev.get("exhaustion", 0),
                    char_id,
                ),
            )

    elif event_type == "set_scene":
        await repo.execute(
            conn,
            "UPDATE campaigns SET current_scene=%s, in_game_date=%s, current_location_id=%s WHERE id=%s",
            (
                prev.get("current_scene"),
                prev.get("in_game_date"),
                prev.get("current_location_id"),
                campaign_id,
            ),
        )

    # write compensating event
    comp_id = await write_event(
        conn, campaign_id, "undo",
        {"reverted_type": event_type, "reverted_event_id": str(row["id"])},
        reason,
        session_id=session_id,
        compensates_event_id=str(row["id"]),
    )

    return {
        "undone_event_id": str(row["id"]),
        "undone_type": event_type,
        "compensating_event_id": comp_id,
    }


async def undo_last_event(reason: str, campaign_id: str | None = None) -> dict:
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _undo_last_event_impl(conn, reason, cid, session_id)
