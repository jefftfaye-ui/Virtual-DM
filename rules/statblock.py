"""SRD statblock helpers. Pure — no DB.

normalize_name: consistent key for name_norm column and lookup queries.
extract_monster_meta: structured fields from a 5e-bits/5e-database monster object.
format_monster_body: human-readable stat block text stored in srd_chunks.body.
"""

from __future__ import annotations

import re


def normalize_name(name: str) -> str:
    """Lowercase, strip non-alphanumeric runs to spaces. Matches ingest + query side."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def extract_monster_meta(m: dict) -> dict:
    """Pull structured combat stats from a 5e-bits monster dict.

    Returns dict suitable for srd_chunks.meta and for start_encounter statblock lookup.
    """
    # AC: list [{value, type}] or bare int
    ac_raw = m.get("armor_class", 10)
    if isinstance(ac_raw, list) and ac_raw:
        ac = ac_raw[0].get("value", 10) if isinstance(ac_raw[0], dict) else int(ac_raw[0])
    else:
        ac = int(ac_raw or 10)

    hp = int(m.get("hit_points", 1))
    hit_dice = m.get("hit_dice") or ""
    dex = int(m.get("dexterity", 10))
    dex_mod = (dex - 10) // 2

    def _clean_list(raw) -> list[str]:
        if not raw:
            return []
        return [str(x).lower().strip() for x in raw if x]

    return {
        "ac": ac,
        "hp": hp,
        "hit_dice": hit_dice,
        "dex_mod": dex_mod,
        "resistances": _clean_list(m.get("damage_resistances")),
        "immunities": _clean_list(m.get("damage_immunities")),
        "vulnerabilities": _clean_list(m.get("damage_vulnerabilities")),
        "condition_immunities": [
            ci["name"].lower() if isinstance(ci, dict) else str(ci).lower()
            for ci in (m.get("condition_immunities") or [])
        ],
    }


def _ability_mod(score: int) -> str:
    mod = (score - 10) // 2
    return f"+{mod}" if mod >= 0 else str(mod)


def format_monster_body(m: dict) -> str:
    """Human-readable stat block for FTS and DM display."""
    lines: list[str] = []

    name = m.get("name", "Unknown")
    size = m.get("size", "")
    mtype = m.get("type", "")
    subtype = m.get("subtype", "")
    alignment = m.get("alignment", "")
    type_line = " ".join(filter(None, [size, mtype, f"({subtype})" if subtype else None]))
    lines.append(f"{name}")
    lines.append(f"{type_line} | {alignment}")

    # AC
    ac_raw = m.get("armor_class", 10)
    if isinstance(ac_raw, list) and ac_raw:
        entry = ac_raw[0]
        ac_str = f"{entry.get('value', '?')} ({entry.get('type', '')})" if isinstance(entry, dict) else str(entry)
    else:
        ac_str = str(ac_raw)

    hp = m.get("hit_points", 0)
    hit_dice = m.get("hit_dice", "")
    speed_dict = m.get("speed", {})
    speed_str = ", ".join(f"{k} {v}" for k, v in speed_dict.items()) if isinstance(speed_dict, dict) else str(speed_dict)
    lines.append(f"AC {ac_str} | HP {hp} ({hit_dice}) | Speed {speed_str}")

    # Abilities
    ab_keys = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
    ab_short = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
    ab_vals = [m.get(k, 10) for k in ab_keys]
    ab_line = "  ".join(f"{s} {v} ({_ability_mod(v)})" for s, v in zip(ab_short, ab_vals))
    lines.append(ab_line)

    # Resistances / immunities
    dr = m.get("damage_resistances") or []
    di = m.get("damage_immunities") or []
    dv = m.get("damage_vulnerabilities") or []
    ci = m.get("condition_immunities") or []
    if dr:
        lines.append(f"Damage Resistances: {', '.join(str(x) for x in dr)}")
    if di:
        lines.append(f"Damage Immunities: {', '.join(str(x) for x in di)}")
    if dv:
        lines.append(f"Damage Vulnerabilities: {', '.join(str(x) for x in dv)}")
    if ci:
        ci_names = [x["name"] if isinstance(x, dict) else str(x) for x in ci]
        lines.append(f"Condition Immunities: {', '.join(ci_names)}")

    # Senses / languages / CR
    senses = m.get("senses", {})
    if isinstance(senses, dict):
        senses_str = ", ".join(f"{k} {v}" for k, v in senses.items())
    else:
        senses_str = str(senses)
    cr = m.get("challenge_rating", "")
    xp = m.get("xp", "")
    lines.append(f"Senses: {senses_str} | CR {cr} ({xp} XP)")

    # Special abilities
    for sa in m.get("special_abilities") or []:
        n = sa.get("name", "")
        d = sa.get("desc", "")
        lines.append(f"Special: {n}. {d}")

    # Actions
    for act in m.get("actions") or []:
        n = act.get("name", "")
        d = act.get("desc", "")
        lines.append(f"Action: {n}. {d}")

    # Legendary actions
    for la in m.get("legendary_actions") or []:
        n = la.get("name", "")
        d = la.get("desc", "")
        lines.append(f"Legendary: {n}. {d}")

    return "\n".join(lines)


def format_spell_body(s: dict) -> str:
    lines = [s.get("name", "")]
    level = s.get("level", 0)
    school = (s.get("school") or {}).get("name", "") if isinstance(s.get("school"), dict) else str(s.get("school", ""))
    level_str = f"Cantrip" if level == 0 else f"Level {level}"
    lines.append(f"{level_str} {school}")
    lines.append(f"Casting Time: {s.get('casting_time', '')} | Range: {s.get('range', '')} | Duration: {s.get('duration', '')}")
    comps = s.get("components") or []
    lines.append(f"Components: {', '.join(comps)}")
    for desc in s.get("desc") or []:
        lines.append(desc)
    if s.get("higher_level"):
        for h in s["higher_level"]:
            lines.append(f"At Higher Levels: {h}")
    return "\n".join(lines)


def format_condition_body(c: dict) -> str:
    lines = [c.get("name", "")]
    for d in c.get("desc") or []:
        lines.append(d)
    return "\n".join(lines)


def format_rule_body(r: dict) -> str:
    lines = [r.get("name", "")]
    lines.append(r.get("desc", ""))
    for sub in r.get("subsections") or []:
        lines.append(f"\n{sub.get('name', '')}")
        lines.append(sub.get("desc", ""))
    return "\n".join(lines)


def format_equipment_body(e: dict) -> str:
    lines = [e.get("name", "")]
    cat = e.get("equipment_category", {})
    cat_name = cat.get("name", "") if isinstance(cat, dict) else str(cat)
    lines.append(cat_name)
    for d in e.get("desc") or []:
        lines.append(d)
    cost = e.get("cost", {})
    if isinstance(cost, dict):
        lines.append(f"Cost: {cost.get('quantity', '')} {cost.get('unit', '')}")
    weight = e.get("weight")
    if weight:
        lines.append(f"Weight: {weight} lb.")
    return "\n".join(lines)
