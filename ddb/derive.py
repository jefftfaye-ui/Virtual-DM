"""Derive character fields from a DDB v5 character JSON snapshot.

Uses charactercheck 0.7.0 (verified on PyPI) for primary derivation.
Falls back to manual derivation if charactercheck validation rejects the snapshot.

Fields derived:
  name, level, class_summary, abilities, saves, skills, max_hp,
  spell_slots, pact_slots, hit_dice, speed, proficiency_bonus

Fields NOT derived (require overrides):
  ac — too many edge cases (magic items, shield, features)
  hp — live mutable state; preserved from existing DB record
  conditions, death_saves, inspiration, inventory (handled separately)
"""

from __future__ import annotations

import json
import re
from typing import Any

# ─── class metadata ───────────────────────────────────────────────────────────

ABBREV = {
    "artificer": "Art", "barbarian": "Bar", "bard": "Brd",
    "cleric": "Clr", "druid": "Drd", "fighter": "Ftr",
    "monk": "Mnk", "paladin": "Pal", "ranger": "Rgr",
    "rogue": "Rog", "sorcerer": "Sor", "warlock": "Wlk", "wizard": "Wiz",
}

# hit die per class name
HIT_DICE = {
    "artificer": 8, "barbarian": 12, "bard": 8, "cleric": 8,
    "druid": 8, "fighter": 10, "monk": 8, "paladin": 10,
    "ranger": 10, "rogue": 8, "sorcerer": 6, "warlock": 8, "wizard": 6,
}

# Warlock pact slot table: {class_level: {"level": slot_level, "max": count}}
_WARLOCK_PACT = {
    1: {"level": 1, "max": 1}, 2: {"level": 1, "max": 2},
    3: {"level": 2, "max": 2}, 4: {"level": 2, "max": 2},
    5: {"level": 3, "max": 2}, 6: {"level": 3, "max": 2},
    7: {"level": 4, "max": 2}, 8: {"level": 4, "max": 2},
    9: {"level": 5, "max": 2}, 10: {"level": 5, "max": 2},
    11: {"level": 5, "max": 3}, 12: {"level": 5, "max": 3},
    13: {"level": 5, "max": 3}, 14: {"level": 5, "max": 3},
    15: {"level": 5, "max": 3}, 16: {"level": 5, "max": 3},
    17: {"level": 5, "max": 4}, 18: {"level": 5, "max": 4},
    19: {"level": 5, "max": 4}, 20: {"level": 5, "max": 4},
}

ABILITY_IDS = {1: "str", 2: "dex", 3: "con", 4: "int", 5: "wis", 6: "cha"}

SKILL_ABILITY = {
    "acrobatics": "dex", "animal-handling": "wis", "arcana": "int",
    "athletics": "str", "deception": "cha", "history": "int",
    "insight": "wis", "intimidation": "cha", "investigation": "int",
    "medicine": "wis", "nature": "int", "perception": "wis",
    "performance": "cha", "persuasion": "cha", "religion": "int",
    "sleight-of-hand": "dex", "stealth": "dex", "survival": "wis",
}

SAVE_SUBTYPES = {
    "strength-saving-throws": "str", "dexterity-saving-throws": "dex",
    "constitution-saving-throws": "con", "intelligence-saving-throws": "int",
    "wisdom-saving-throws": "wis", "charisma-saving-throws": "cha",
}


# ─── primary: charactercheck ──────────────────────────────────────────────────

def _slots_list_to_dict(slots_list: list[int] | None) -> dict[str, dict]:
    if not slots_list:
        return {}
    result = {}
    for i, n in enumerate(slots_list):
        if n and n > 0:
            result[str(i + 1)] = {"max": int(n), "used": 0}
    return result


def _derive_via_charactercheck(data: dict) -> dict:
    """Use charactercheck 0.7.0 to derive fields. Raises on failure."""
    from charactercheck.engine import build
    from charactercheck import source as cc_source

    # charactercheck expects the `data` dict (not the wrapper)
    filtered, _ = cc_source.privacy_filter_with_coverage(data)
    W = build(filtered, _privacy_filtered=True)

    # abilities
    abilities: dict[str, int] = {}
    raw_A = W.get("A") or {}
    for ab in ("str", "dex", "con", "int", "wis", "cha"):
        abilities[ab] = int((raw_A.get(ab) or {}).get("score", 10))

    con_mod = (abilities.get("con", 10) - 10) // 2

    # saves (proficiency flag per ability)
    saves: dict[str, bool] = {}
    raw_saves = W.get("saves") or {}
    for ab in ("str", "dex", "con", "int", "wis", "cha"):
        sv = raw_saves.get(ab) or {}
        saves[ab] = bool(sv.get("proficient"))

    # skills (subType → proficiency level)
    skills: dict[str, str] = {}
    raw_skills = W.get("skills") or {}
    for skill_name in SKILL_ABILITY:
        sk = raw_skills.get(skill_name) or {}
        prof = sk.get("proficiency") or "none"
        skills[skill_name] = prof  # "none" | "proficiency" | "expertise"

    # level + class_summary
    classes = data.get("classes") or []
    total_level = sum(c.get("level", 0) for c in classes)
    prof_bonus = 2 + (total_level - 1) // 4

    parts = []
    for c in classes:
        defn = (c.get("definition") or {})
        cn = (defn.get("name") or "").strip().lower()
        lvl = c.get("level", 0)
        abbr = ABBREV.get(cn, cn[:3].title())
        parts.append(f"{abbr} {lvl}")
    class_summary = " / ".join(parts) if parts else "Unknown"

    # max_hp from charactercheck workspace
    hp_w = W.get("hp") or {}
    max_hp: int = int(hp_w.get("max", 0)) or _manual_max_hp(data, abilities)

    # hit dice
    hit_dice: dict[str, dict] = {}
    for c in classes:
        defn = c.get("definition") or {}
        cn = (defn.get("name") or "").strip().lower()
        lvl = c.get("level", 0)
        die_val = defn.get("hitDice") or HIT_DICE.get(cn, 8)
        die_key = f"d{die_val}"
        if die_key in hit_dice:
            hit_dice[die_key]["max"] += lvl
        else:
            hit_dice[die_key] = {"max": lvl, "used": 0}

    # spell slots from charactercheck workspace
    slots_list = W.get("slots") or []
    spell_slots = _slots_list_to_dict(slots_list)

    # pact slots: warlock class level
    pact_slots = None
    for c in classes:
        cn = ((c.get("definition") or {}).get("name") or "").lower()
        if cn == "warlock":
            wlk_lvl = min(c.get("level", 1), 20)
            pact = _WARLOCK_PACT.get(wlk_lvl, {"level": 5, "max": 4})
            pact_slots = {**pact, "used": 0}
            break

    # speed
    speed = _extract_speed(data)

    # name
    name = data.get("name") or "Unknown"

    return {
        "name": name,
        "level": total_level,
        "class_summary": class_summary,
        "proficiency_bonus": prof_bonus,
        "abilities": abilities,
        "saves": saves,
        "skills": skills,
        "max_hp": max_hp,
        "hit_dice": hit_dice,
        "spell_slots": spell_slots,
        "pact_slots": pact_slots,
        "speed": speed,
        "ac": None,  # never derived — use overrides
        "_source": "charactercheck",
    }


# ─── fallback: manual derivation ──────────────────────────────────────────────

def _resolve_ability_scores(data: dict) -> dict[str, int]:
    stats = {s["id"]: (s.get("value") or 0) for s in (data.get("stats") or [])}
    bonus = {s["id"]: (s.get("value") or 0) for s in (data.get("bonusStats") or [])}
    override = {s["id"]: s.get("value") for s in (data.get("overrideStats") or [])}
    result = {}
    for id_, ab in ABILITY_IDS.items():
        if override.get(id_) is not None:
            result[ab] = int(override[id_])
        else:
            result[ab] = int(stats.get(id_, 10)) + int(bonus.get(id_, 0))
    return result


def _extract_speed(data: dict) -> int:
    race = data.get("race") or {}
    speeds = race.get("weightSpeeds") or {}
    normal = speeds.get("normal") or {}
    walk = normal.get("walk")
    if walk:
        return int(walk)
    # try modifiers for speed bonus
    return 30  # default


def _manual_max_hp(data: dict, abilities: dict[str, int]) -> int:
    hpi = data.get("hitPointInfo") or {}
    base = hpi.get("baseHitPoints") or 0
    con_bonus = hpi.get("constitutionHitPointBonus") or 0
    bonus = hpi.get("bonusHitPoints") or 0
    if base:
        return int(base) + int(con_bonus) + int(bonus)
    # manual fallback
    classes = data.get("classes") or []
    total = 0
    con_mod = (abilities.get("con", 10) - 10) // 2
    for c in classes:
        defn = c.get("definition") or {}
        cn = (defn.get("name") or "").lower()
        lvl = c.get("level", 0)
        die = defn.get("hitDice") or HIT_DICE.get(cn, 8)
        first = die  # max die at level 1
        rest = ((die // 2) + 1) * max(0, lvl - 1)
        total += first + rest + con_mod * lvl
    return max(1, total)


def _collect_proficiencies(data: dict) -> tuple[dict[str, bool], dict[str, str]]:
    """Parse DDB modifiers to find save proficiencies and skill proficiencies."""
    saves: dict[str, bool] = {ab: False for ab in ABILITY_IDS.values()}
    skills: dict[str, str] = {sk: "none" for sk in SKILL_ABILITY}

    all_mods: list[dict] = []
    for bucket in (data.get("modifiers") or {}).values():
        if isinstance(bucket, list):
            all_mods.extend(bucket)

    for mod in all_mods:
        t = (mod.get("type") or "").lower()
        sub = (mod.get("subType") or "").lower()

        if t == "proficiency":
            if sub in SAVE_SUBTYPES:
                saves[SAVE_SUBTYPES[sub]] = True
            elif sub in skills:
                skills[sub] = "proficiency"

        elif t in ("expertise", "double-proficiency"):
            if sub in skills:
                skills[sub] = "expertise"

    return saves, skills


def _derive_manual(data: dict) -> dict:
    abilities = _resolve_ability_scores(data)
    classes = data.get("classes") or []
    total_level = sum(c.get("level", 0) for c in classes)
    prof_bonus = 2 + max(0, total_level - 1) // 4

    parts = []
    hit_dice: dict = {}
    for c in classes:
        defn = c.get("definition") or {}
        cn = (defn.get("name") or "").strip().lower()
        lvl = c.get("level", 0)
        abbr = ABBREV.get(cn, cn[:3].title())
        parts.append(f"{abbr} {lvl}")
        die_val = defn.get("hitDice") or HIT_DICE.get(cn, 8)
        die_key = f"d{die_val}"
        if die_key in hit_dice:
            hit_dice[die_key]["max"] += lvl
        else:
            hit_dice[die_key] = {"max": lvl, "used": 0}

    saves, skills = _collect_proficiencies(data)
    max_hp = _manual_max_hp(data, abilities)

    # spell slots via charactercheck helpers (fallback)
    try:
        from charactercheck.engine import expected_slots
        slots_list = expected_slots(classes) or []
        spell_slots = _slots_list_to_dict(slots_list)
    except Exception:
        spell_slots = {}

    pact_slots = None
    for c in classes:
        cn = ((c.get("definition") or {}).get("name") or "").lower()
        if cn == "warlock":
            wlk_lvl = min(c.get("level", 1), 20)
            pact = _WARLOCK_PACT.get(wlk_lvl, {"level": 5, "max": 4})
            pact_slots = {**pact, "used": 0}
            break

    return {
        "name": data.get("name") or "Unknown",
        "level": total_level,
        "class_summary": " / ".join(parts) if parts else "Unknown",
        "proficiency_bonus": prof_bonus,
        "abilities": abilities,
        "saves": saves,
        "skills": skills,
        "max_hp": max_hp,
        "hit_dice": hit_dice,
        "spell_slots": spell_slots,
        "pact_slots": pact_slots,
        "speed": _extract_speed(data),
        "ac": None,
        "_source": "manual",
    }


# ─── public API ───────────────────────────────────────────────────────────────

def derive(snapshot: dict) -> dict:
    """Derive character fields from a DDB v5 character data dict.

    The `snapshot` arg is the `data` object from the DDB API response
    (i.e., the dict returned by ddb.client.fetch_character()).

    Returns a partial `characters` row. Fields marked None must be set
    via overrides (especially ac).

    Never reads from or writes to the DB.
    """
    try:
        result = _derive_via_charactercheck(snapshot)
    except Exception as e:
        result = _derive_manual(snapshot)
        result["_charactercheck_error"] = str(e)

    # extract DDB ID + player currency → gold
    result["ddb_id"] = str(snapshot.get("id") or "")
    currencies = snapshot.get("currencies") or {}
    gold = (
        int(currencies.get("gp") or 0)
        + int(currencies.get("pp") or 0) * 10
        + int(currencies.get("ep") or 0) // 2
        + int(currencies.get("sp") or 0) // 10
        + int(currencies.get("cp") or 0) // 100
    )
    result["gold"] = gold

    return result


def diff(derived: dict, existing: dict) -> dict:
    """Return {field: (derived_value, existing_value)} for mismatches.

    Used by import script to surface what changed and what needs manual overrides.
    """
    compare_keys = ("level", "class_summary", "max_hp", "speed", "abilities",
                    "spell_slots", "pact_slots", "hit_dice")
    mismatches = {}
    for k in compare_keys:
        dv = derived.get(k)
        ev = existing.get(k)
        if dv != ev:
            mismatches[k] = {"derived": dv, "existing": ev}
    return mismatches
