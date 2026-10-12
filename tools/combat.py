"""Combat tools: start_encounter, add_combatant, update_combatant, next_turn, end_encounter.

Each public tool opens its own repo.tx(). _impl variants accept a caller conn for tests
and for calls from other tools within an existing transaction.

Phase 5 note: statblock_ref SRD lookups not wired yet — supply ac + hp explicitly for now.
"""

from __future__ import annotations

import json
from typing import Any

from db import repo
from rules import damage as dmg_rules
from rules.turn_order import (
    CombatantView,
    assign_tiebreaks,
    sort_initiative,
    is_skippable,
    next_index,
)
from tools._util import (
    resolve_campaign_id,
    to_str,
    write_event,
    get_campaign,
    get_active_session_id,
)
from tools.dice import _roll_impl
from tools.rules import _lookup_monster_meta
from tools.state import _update_character_impl


# ─── shared helpers ────────────────────────────────────────────────────────────

def _cview(row: dict) -> CombatantView:
    return CombatantView(
        id=str(row["id"]),
        name=row["name"],
        kind=row["kind"],
        initiative=row["initiative"],
        dex_mod=row.get("dex_mod") or 0,
        tiebreak=row.get("tiebreak"),
        status=row["status"],
        hp=row["hp"],
        stable=bool(row.get("stable", False)),
    )


async def _load_ordered_combatants(conn, encounter_id: str) -> list[dict]:
    """Load + return combatants in initiative order (no sorting in SQL — we sort in Python)."""
    return await repo.fetchall(
        conn,
        "SELECT * FROM combatants WHERE encounter_id = %s",
        (encounter_id,),
    )


async def _ensure_active(conn, encounter_id: str) -> dict | None:
    enc = await repo.fetchone(
        conn, "SELECT * FROM encounters WHERE id = %s", (encounter_id,)
    )
    if not enc or enc["status"] != "active":
        return None
    return enc


async def _clear_concentration_effects(conn, encounter_id: str, source_combatant_id: str) -> list[dict]:
    """Delete all concentration=true effects sourced from this combatant. Return deleted list."""
    effects = await repo.fetchall(
        conn,
        "SELECT id, name, target_combatant_id FROM effects "
        "WHERE encounter_id=%s AND source_combatant_id=%s AND concentration=true",
        (encounter_id, source_combatant_id),
    )
    for eff in effects:
        await repo.execute(conn, "DELETE FROM effects WHERE id=%s", (eff["id"],))
    return [{"id": str(e["id"]), "name": e["name"]} for e in effects]


async def _tick_effects(
    conn,
    encounter_id: str,
    prev_combatant_id: str | None,
    new_combatant_id: str,
) -> list[dict]:
    """Tick effects at turn boundary. Return expired effects."""
    expired: list[dict] = []

    # End-of-turn: effects anchored to the combatant whose turn just ended
    if prev_combatant_id:
        effs = await repo.fetchall(
            conn,
            "SELECT * FROM effects WHERE encounter_id=%s AND anchor_combatant_id=%s AND ends='end_of_turn'",
            (encounter_id, prev_combatant_id),
        )
        for eff in effs:
            new_left = eff["rounds_left"] - 1
            if new_left <= 0:
                await repo.execute(conn, "DELETE FROM effects WHERE id=%s", (eff["id"],))
                expired.append({
                    "id": str(eff["id"]), "name": eff["name"],
                    "target_combatant_id": str(eff["target_combatant_id"]),
                    "ends": "end_of_turn",
                })
            else:
                await repo.execute(
                    conn, "UPDATE effects SET rounds_left=%s WHERE id=%s", (new_left, eff["id"])
                )

    # Start-of-turn: effects anchored to the combatant whose turn is starting
    effs = await repo.fetchall(
        conn,
        "SELECT * FROM effects WHERE encounter_id=%s AND anchor_combatant_id=%s AND ends='start_of_turn'",
        (encounter_id, new_combatant_id),
    )
    for eff in effs:
        new_left = eff["rounds_left"] - 1
        if new_left <= 0:
            await repo.execute(conn, "DELETE FROM effects WHERE id=%s", (eff["id"],))
            expired.append({
                "id": str(eff["id"]), "name": eff["name"],
                "target_combatant_id": str(eff["target_combatant_id"]),
                "ends": "start_of_turn",
            })
        else:
            await repo.execute(
                conn, "UPDATE effects SET rounds_left=%s WHERE id=%s", (new_left, eff["id"])
            )

    return expired


# ─── P3.1: start_encounter ─────────────────────────────────────────────────────

async def _start_encounter_impl(
    conn,
    name: str,
    monsters: list[dict],
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    # Insert encounter with turn_index = -1 (no one has gone yet)
    enc_row = await repo.fetchone(
        conn,
        "INSERT INTO encounters (campaign_id, name, round, turn_index) VALUES (%s,%s,1,-1) RETURNING id",
        (campaign_id, name),
    )
    encounter_id = str(enc_row["id"])

    combatant_rows: list[dict] = []

    campaign_row = await repo.fetchone(
        conn, "SELECT edition, settings FROM campaigns WHERE id=%s", (campaign_id,)
    )
    edition = str((campaign_row or {}).get("edition", "2014"))
    settings = (campaign_row or {}).get("settings") or {}
    hp_mode = settings.get("monster_hp_mode", "average")

    # Expand monster entries
    for entry in monsters:
        count = entry.get("count", 1)
        base_name = entry.get("name", "Monster")
        ac = entry.get("ac")
        hp = entry.get("hp")
        dex_mod = entry.get("dex_mod", 0)
        resistances = list(entry.get("resistances") or [])
        immunities = list(entry.get("immunities") or [])
        vulnerabilities = list(entry.get("vulnerabilities") or [])
        statblock_ref = entry.get("statblock_ref")
        hit_dice_expr = entry.get("hit_dice_expr")

        # Phase 5: try SRD statblock lookup if statblock_ref provided or name matches
        if ac is None or hp is None or statblock_ref:
            lookup_name = statblock_ref or base_name
            meta = await _lookup_monster_meta(conn, lookup_name, edition)
            if meta:
                ac = ac if ac is not None else meta["ac"]
                hp = hp if hp is not None else meta["hp"]
                dex_mod = entry.get("dex_mod", meta.get("dex_mod", 0))
                if not resistances:
                    resistances = meta.get("resistances") or []
                if not immunities:
                    immunities = meta.get("immunities") or []
                if not vulnerabilities:
                    vulnerabilities = meta.get("vulnerabilities") or []
                if not hit_dice_expr:
                    hit_dice_expr = meta.get("hit_dice") or None
            elif ac is None or hp is None:
                return {
                    "error": f"monster '{base_name}' requires explicit ac and hp "
                             f"(SRD lookup for '{lookup_name}' returned no results)",
                    "hint": "pass ac=… and hp=… or run scripts/ingest_srd.py first",
                }

        for i in range(1, count + 1):
            m_name = f"{base_name} {i}" if count > 1 else base_name

            # HP mode: use hit_dice_expr if rolled mode, else average
            actual_hp = hp
            if hit_dice_expr and hp_mode == "rolled":
                roll_result = await _roll_impl(
                    conn, hit_dice_expr, f"HP roll for {m_name}", "DM", campaign_id,
                    session_id=session_id,
                )
                if "error" not in roll_result:
                    actual_hp = max(1, roll_result["total"])

            # Roll initiative: 1d20 + dex_mod
            expr = f"1d20{'+' if dex_mod >= 0 else ''}{dex_mod}" if dex_mod != 0 else "1d20"
            init_roll = await _roll_impl(
                conn, expr, f"initiative for {m_name}", m_name, campaign_id,
                session_id=session_id,
            )
            initiative = init_roll.get("total", 10)

            row = await repo.fetchone(
                conn,
                """
                INSERT INTO combatants (
                    encounter_id, kind, name, initiative, dex_mod, ac, max_hp, hp, temp_hp,
                    resistances, immunities, vulnerabilities, status, statblock_ref
                ) VALUES (%s,'monster',%s,%s,%s,%s,%s,%s,0,%s,%s,%s,'active',%s)
                RETURNING id, name, initiative, hp, max_hp, ac, kind
                """,
                (
                    encounter_id, m_name, initiative, dex_mod, ac, actual_hp, actual_hp,
                    resistances, immunities, vulnerabilities, statblock_ref,
                ),
            )
            combatant_rows.append(dict(row))

    await write_event(
        conn, campaign_id, "start_encounter",
        {"encounter_id": encounter_id, "name": name, "monster_count": len(combatant_rows)},
        reason, session_id=session_id,
    )

    result_out = to_str({
        "encounter_id": encounter_id,
        "combatants": [
            {
                "id": str(r["id"]), "name": r["name"], "kind": r["kind"],
                "initiative": r["initiative"], "hp": r["hp"], "max_hp": r["max_hp"],
            }
            for r in combatant_rows
        ],
        "note": "Add PCs via add_combatant with kind='pc' and their character_id as ref_id. "
                "Set PC initiatives via update_combatant(initiative=…).",
    })
    await repo.store_idempotent(conn, campaign_id, request_id, result_out)
    return result_out


async def start_encounter(
    name: str,
    monsters: list[dict],
    reason: str,
    campaign_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Start a combat encounter. monsters: [{name, count, ac, hp, dex_mod?, resistances?, ...}].
    PCs added separately via add_combatant. SRD statblock lookup available in Phase 5."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _start_encounter_impl(conn, name, monsters, reason, cid, session_id, request_id)


# ─── P3.2: add_combatant ───────────────────────────────────────────────────────

async def _add_combatant_impl(
    conn,
    encounter_id: str,
    kind: str,
    name: str,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    *,
    ac: int | None = None,
    hp: int | None = None,
    dex_mod: int = 0,
    initiative: int | None = None,
    ref_id: str | None = None,
    resistances: list[str] | None = None,
    immunities: list[str] | None = None,
    vulnerabilities: list[str] | None = None,
    statblock_ref: str | None = None,
) -> dict:
    enc = await _ensure_active(conn, encounter_id)
    if not enc:
        return {"error": "encounter not found or not active", "hint": f"id={encounter_id}"}

    if kind == "pc":
        if not ref_id:
            return {"error": "pc combatant requires ref_id (character UUID)"}
        char = await repo.fetchone(conn, "SELECT * FROM characters WHERE id=%s", (ref_id,))
        if not char:
            return {"error": f"character {ref_id} not found"}
        ac = char["ac"] or ac or 10
        hp = char["hp"]
        max_hp = char["max_hp"]
        dex_mod = ((char.get("abilities") or {}).get("dex", 10) - 10) // 2
        resistances = list(char.get("resistances") or [])
        immunities = list(char.get("immunities") or [])
        vulnerabilities = list(char.get("vulnerabilities") or [])
    else:
        if ac is None or hp is None:
            return {"error": f"monster/npc combatant requires ac and hp"}
        max_hp = hp

    # Roll initiative for monsters if not provided
    actual_initiative = initiative
    if actual_initiative is None and kind != "pc":
        expr = f"1d20{'+' if dex_mod >= 0 else ''}{dex_mod}" if dex_mod != 0 else "1d20"
        init_roll = await _roll_impl(
            conn, expr, f"initiative for {name}", name, campaign_id,
            session_id=session_id,
        )
        actual_initiative = init_roll.get("total", 10)

    row = await repo.fetchone(
        conn,
        """
        INSERT INTO combatants (
            encounter_id, kind, ref_id, name, initiative, dex_mod, ac, max_hp, hp, temp_hp,
            resistances, immunities, vulnerabilities, status, statblock_ref
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,'active',%s)
        RETURNING id, name, kind, initiative, hp, max_hp
        """,
        (
            encounter_id, kind, ref_id, name, actual_initiative, dex_mod, ac, max_hp, hp,
            resistances or [], immunities or [], vulnerabilities or [], statblock_ref,
        ),
    )

    await write_event(
        conn, campaign_id, "add_combatant",
        {"encounter_id": encounter_id, "combatant_id": str(row["id"]), "kind": kind, "name": name},
        reason, session_id=session_id,
    )

    return to_str({
        "combatant_id": str(row["id"]),
        "name": row["name"],
        "kind": row["kind"],
        "initiative": row["initiative"],
        "hp": row["hp"],
        "max_hp": row["max_hp"],
    })


async def add_combatant(
    encounter_id: str,
    kind: str,
    name: str,
    reason: str,
    campaign_id: str | None = None,
    request_id: str | None = None,
    ac: int | None = None,
    hp: int | None = None,
    dex_mod: int = 0,
    initiative: int | None = None,
    ref_id: str | None = None,
    resistances: list[str] | None = None,
    immunities: list[str] | None = None,
    vulnerabilities: list[str] | None = None,
    statblock_ref: str | None = None,
) -> dict:
    """Add a combatant to an active encounter. kind: pc | monster | npc.
    PC requires ref_id (character UUID). Monsters roll initiative if not given."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _add_combatant_impl(
            conn, encounter_id, kind, name, reason, cid, session_id,
            ac=ac, hp=hp, dex_mod=dex_mod, initiative=initiative, ref_id=ref_id,
            resistances=resistances, immunities=immunities, vulnerabilities=vulnerabilities,
            statblock_ref=statblock_ref,
        )


# ─── P3.3: update_combatant ────────────────────────────────────────────────────

async def _update_combatant_impl(
    conn,
    combatant_id: str,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
    *,
    edition: str = "2014",
    massive_damage_enabled: bool = True,
    damage: dict | None = None,
    heal: int = 0,
    add_conditions: list[str] | None = None,
    remove_conditions: list[str] | None = None,
    initiative: int | None = None,
    status: str | None = None,
    start_concentration: str | None = None,
    end_concentration: bool = False,
    add_effect: dict | None = None,
    remove_effect: str | None = None,
    nonlethal: bool = False,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    comb = await repo.fetchone(
        conn, "SELECT * FROM combatants WHERE id=%s FOR UPDATE", (combatant_id,)
    )
    if not comb:
        return {"error": "combatant not found", "hint": f"id={combatant_id}"}

    encounter_id = str(comb["encounter_id"])
    response: dict[str, Any] = {"combatant_id": combatant_id}
    ended_concentration_effects: list[dict] = []

    # ── PC path: proxy to update_character ────────────────────────────────────
    if comb["kind"] == "pc" and comb.get("ref_id"):
        char_result = await _update_character_impl(
            conn, str(comb["ref_id"]), reason, campaign_id, session_id, None,
            edition=edition, massive_damage_enabled=massive_damage_enabled,
            damage=damage, heal=heal,
            add_conditions=add_conditions, remove_conditions=remove_conditions,
            start_concentration=start_concentration, end_concentration=end_concentration,
        )
        if "error" in char_result:
            return char_result

        # Mirror HP + conditions back to combatant row
        await repo.execute(
            conn,
            "UPDATE combatants SET hp=%s, temp_hp=%s, conditions=%s, concentrating_on=%s WHERE id=%s",
            (
                char_result["hp_after"],
                char_result["temp_hp_after"],
                char_result["conditions"],
                char_result["concentrating_on"],
                combatant_id,
            ),
        )

        if char_result.get("dropped"):
            await repo.execute(
                conn, "UPDATE combatants SET status='down' WHERE id=%s", (combatant_id,)
            )
            response["dropped"] = True

        if char_result.get("ended_concentration") or (end_concentration and comb.get("concentrating_on")):
            ended_concentration_effects = await _clear_concentration_effects(
                conn, encounter_id, combatant_id
            )

        response.update({k: v for k, v in char_result.items() if k not in ("character_id",)})
        response["combatant_id"] = combatant_id

    else:
        # ── Monster / NPC path ────────────────────────────────────────────────
        hp = comb["hp"]
        max_hp = comb["max_hp"]
        temp_hp_val = comb["temp_hp"]
        conditions = list(comb.get("conditions") or [])
        concentrating_on = comb.get("concentrating_on")

        if damage is not None:
            target = dmg_rules.TargetState(
                hp=hp, max_hp=max_hp, temp_hp=temp_hp_val,
                resistances=list(comb.get("resistances") or []),
                immunities=list(comb.get("immunities") or []),
                vulnerabilities=list(comb.get("vulnerabilities") or []),
                concentrating=bool(concentrating_on),
            )
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
                ended_concentration_effects = await _clear_concentration_effects(
                    conn, encounter_id, combatant_id
                )
            if out.concentration_check:
                response["concentration_check"] = out.concentration_check
            response.update({
                "resisted": out.resisted, "immune": out.immune,
                "vulnerable": out.vulnerable, "temp_absorbed": out.temp_absorbed,
            })
            if out.dropped or out.dead:
                response["dropped"] = True

        if heal > 0:
            hp = min(max_hp, hp + heal)

        # Determine new status for monsters
        new_status = comb["status"]
        if hp == 0 and comb["status"] == "active":
            new_status = "down" if (nonlethal and damage and damage.get("type") not in ("fire", "acid", "poison", "lightning", "cold", "psychic", "radiant", "necrotic", "thunder", "force")) else "dead"
        if status in ("fled", "removed", "active", "down", "dead"):
            new_status = status

        # Conditions
        from tools.state import _apply_conditions
        if add_conditions or remove_conditions:
            conditions = _apply_conditions(conditions, add_conditions, remove_conditions)

        # Concentration
        if start_concentration is not None:
            concentrating_on = start_concentration
        if end_concentration:
            if concentrating_on:
                ended_concentration_effects = await _clear_concentration_effects(
                    conn, encounter_id, combatant_id
                )
            concentrating_on = None

        # Initiative
        actual_initiative = initiative if initiative is not None else comb["initiative"]

        await repo.execute(
            conn,
            "UPDATE combatants SET hp=%s, temp_hp=%s, conditions=%s, concentrating_on=%s, status=%s, initiative=%s WHERE id=%s",
            (hp, temp_hp_val, conditions, concentrating_on, new_status, actual_initiative, combatant_id),
        )

        response.update({
            "hp_after": hp, "temp_hp_after": temp_hp_val,
            "status": new_status, "conditions": conditions,
        })

    # ── Effects ──────────────────────────────────────────────────────────────
    if add_effect:
        anchor = add_effect.get("anchor_combatant_id") or combatant_id
        eff_row = await repo.fetchone(
            conn,
            """
            INSERT INTO effects (
                encounter_id, target_combatant_id, source_combatant_id, anchor_combatant_id,
                name, ends, rounds_left, concentration
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                encounter_id, combatant_id,
                add_effect.get("source_combatant_id"),
                anchor,
                add_effect["name"],
                add_effect.get("ends", "end_of_turn"),
                add_effect.get("rounds_left", 1),
                bool(add_effect.get("concentration", False)),
            ),
        )
        response["effect_added"] = {"id": str(eff_row["id"]), "name": add_effect["name"]}

    if remove_effect:
        await repo.execute(conn, "DELETE FROM effects WHERE id=%s", (remove_effect,))
        response["effect_removed"] = remove_effect

    if ended_concentration_effects:
        response["concentration_effects_ended"] = ended_concentration_effects

    await write_event(
        conn, campaign_id, "update_combatant",
        {"combatant_id": combatant_id, "damage": damage, "heal": heal, "status": status},
        reason, session_id=session_id,
    )

    await repo.store_idempotent(conn, campaign_id, request_id, to_str(response))
    return to_str(response)


async def update_combatant(
    combatant_id: str,
    reason: str,
    campaign_id: str | None = None,
    request_id: str | None = None,
    damage: dict | None = None,
    heal: int = 0,
    add_conditions: list[str] | None = None,
    remove_conditions: list[str] | None = None,
    initiative: int | None = None,
    status: str | None = None,
    start_concentration: str | None = None,
    end_concentration: bool = False,
    add_effect: dict | None = None,
    remove_effect: str | None = None,
    nonlethal: bool = False,
) -> dict:
    """Apply damage/heal/conditions/effects to a combatant. PC combatants proxy to update_character."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        campaign = await get_campaign(conn, cid)
        edition = str((campaign or {}).get("edition", "2014"))
        massive = ((campaign or {}).get("settings") or {}).get("massive_damage", True)
        session_id = await get_active_session_id(conn, cid)
        return await _update_combatant_impl(
            conn, combatant_id, reason, cid, session_id, request_id,
            edition=edition, massive_damage_enabled=massive,
            damage=damage, heal=heal,
            add_conditions=add_conditions, remove_conditions=remove_conditions,
            initiative=initiative, status=status,
            start_concentration=start_concentration, end_concentration=end_concentration,
            add_effect=add_effect, remove_effect=remove_effect,
            nonlethal=nonlethal,
        )


# ─── P3.4: next_turn ───────────────────────────────────────────────────────────

async def _next_turn_impl(
    conn,
    encounter_id: str,
    campaign_id: str,
    session_id: str | None,
) -> dict:
    enc = await _ensure_active(conn, encounter_id)
    if not enc:
        return {"error": "encounter not found or not active"}

    rows = await _load_ordered_combatants(conn, encounter_id)
    if not rows:
        return {"error": "no combatants in encounter"}

    views = [_cview(r) for r in rows]

    # Assign any missing tiebreaks and persist them
    updated = assign_tiebreaks(views)
    for v in updated:
        if v.tiebreak is not None:
            orig = next((r for r in rows if str(r["id"]) == v.id), None)
            if orig and orig.get("tiebreak") is None:
                await repo.execute(
                    conn, "UPDATE combatants SET tiebreak=%s WHERE id=%s", (v.tiebreak, v.id)
                )

    ordered = sort_initiative(views)

    current_idx = enc["turn_index"]  # -1 = no one has gone yet

    # Advance index
    try:
        new_idx, rounds_advanced = next_index(ordered, current_idx)
    except ValueError as e:
        return {"error": str(e)}

    new_round = enc["round"] + rounds_advanced
    new_combatant = ordered[new_idx]

    # Identify previous combatant (for end-of-turn effect ticking)
    prev_combatant_id: str | None = None
    if current_idx >= 0 and current_idx < len(ordered):
        prev_combatant_id = ordered[current_idx].id

    # Tick effects at turn boundary
    expired = await _tick_effects(conn, encounter_id, prev_combatant_id, new_combatant.id)

    # Update encounter state
    await repo.execute(
        conn,
        "UPDATE encounters SET round=%s, turn_index=%s WHERE id=%s",
        (new_round, new_idx, encounter_id),
    )

    # death_save_due: PC at 0 HP, not stable, not dead
    death_save_due = (
        new_combatant.kind == "pc"
        and new_combatant.hp == 0
        and not new_combatant.stable
        and new_combatant.status != "dead"
    )

    hp_status = "up" if new_combatant.hp > 0 else ("stable" if new_combatant.stable else "down")

    await write_event(
        conn, campaign_id, "next_turn",
        {
            "encounter_id": encounter_id,
            "round": new_round,
            "turn_index": new_idx,
            "current_combatant": new_combatant.id,
            "expired_effects": [e["id"] for e in expired],
        },
        "next turn", session_id=session_id,
    )

    return to_str({
        "round": new_round,
        "turn_index": new_idx,
        "current": {
            "combatant_id": new_combatant.id,
            "name": new_combatant.name,
            "kind": new_combatant.kind,
            "hp_status": hp_status,
            "hp": new_combatant.hp,
        },
        "expired_effects": expired,
        "death_save_due": death_save_due,
    })


async def next_turn(
    encounter_id: str | None = None,
    campaign_id: str | None = None,
) -> dict:
    """Advance to the next combatant's turn. Ticks effects, handles death_save_due for downed PCs."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        if not encounter_id:
            # find active encounter
            enc = await repo.fetchone(
                conn,
                "SELECT id FROM encounters WHERE campaign_id=%s AND status='active' ORDER BY created_at DESC LIMIT 1",
                (cid,),
            )
            if not enc:
                return {"error": "no active encounter", "hint": "start one with start_encounter"}
            encounter_id = str(enc["id"])
        session_id = await get_active_session_id(conn, cid)
        return await _next_turn_impl(conn, encounter_id, cid, session_id)


# ─── P3.5: end_encounter ───────────────────────────────────────────────────────

async def _end_encounter_impl(
    conn,
    encounter_id: str,
    reason: str,
    outcome_summary: str,
    campaign_id: str,
    session_id: str | None,
) -> dict:
    enc = await repo.fetchone(conn, "SELECT * FROM encounters WHERE id=%s", (encounter_id,))
    if not enc:
        return {"error": "encounter not found"}
    if enc["status"] == "ended":
        return {"error": "encounter already ended"}

    # Collect concentration effects so we can clear concentrating_on on PCs
    conc_effects = await repo.fetchall(
        conn,
        "SELECT DISTINCT source_combatant_id FROM effects WHERE encounter_id=%s AND concentration=true",
        (encounter_id,),
    )
    source_ids = [str(r["source_combatant_id"]) for r in conc_effects if r["source_combatant_id"]]

    # Clear concentrating_on on PC characters whose concentration was tracked here
    for src_id in source_ids:
        comb = await repo.fetchone(conn, "SELECT kind, ref_id FROM combatants WHERE id=%s", (src_id,))
        if comb and comb["kind"] == "pc" and comb.get("ref_id"):
            await repo.execute(
                conn,
                "UPDATE characters SET concentrating_on=NULL WHERE id=%s",
                (comb["ref_id"],),
            )

    # Delete all effects for this encounter
    await repo.execute(conn, "DELETE FROM effects WHERE encounter_id=%s", (encounter_id,))

    # End encounter
    await repo.execute(
        conn, "UPDATE encounters SET status='ended' WHERE id=%s", (encounter_id,)
    )

    await write_event(
        conn, campaign_id, "end_encounter",
        {"encounter_id": encounter_id, "outcome": outcome_summary},
        reason, session_id=session_id,
    )

    return {"encounter_id": encounter_id, "status": "ended", "outcome": outcome_summary}


async def end_encounter(
    encounter_id: str,
    reason: str,
    outcome_summary: str,
    campaign_id: str | None = None,
) -> dict:
    """End a combat encounter. Clears all effects and encounter-tracked concentration."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _end_encounter_impl(conn, encounter_id, reason, outcome_summary, cid, session_id)
