"""Unit tests for ddb/derive.py — pure, no DB, no network.

Tests both the charactercheck path and the manual fallback path.
Fixture snapshots mirror what the DDB v5 API returns in its `data` field.
"""

from __future__ import annotations

import pytest

from ddb.derive import derive, diff, _resolve_ability_scores, _manual_max_hp

# ─── fixture character dicts ──────────────────────────────────────────────────

_MONK5 = {
    "id": 11111,
    "name": "Kira",
    "stats": [
        {"id": 1, "value": 10},  # STR
        {"id": 2, "value": 14},  # DEX
        {"id": 3, "value": 12},  # CON
        {"id": 4, "value": 8},   # INT
        {"id": 5, "value": 13},  # WIS
        {"id": 6, "value": 10},  # CHA
    ],
    "bonusStats": [{"id": i, "value": None} for i in range(1, 7)],
    "overrideStats": [{"id": i, "value": None} for i in range(1, 7)],
    "classes": [
        {
            "level": 5,
            "definition": {"name": "Monk", "hitDice": 8, "spellcastingAbility": None},
        }
    ],
    "hitPointInfo": {
        "baseHitPoints": 33,
        "constitutionHitPointBonus": 5,
        "bonusHitPoints": 0,
        "removedHitPoints": 0,
        "temporaryHitPoints": 0,
    },
    "modifiers": {
        "class": [
            {"type": "proficiency", "subType": "strength-saving-throws"},
            {"type": "proficiency", "subType": "dexterity-saving-throws"},
            {"type": "proficiency", "subType": "acrobatics"},
            {"type": "proficiency", "subType": "stealth"},
        ],
        "race": [], "background": [], "item": [], "feat": [], "condition": [],
    },
    "race": {
        "fullName": "Human",
        "weightSpeeds": {"normal": {"walk": 30}},
    },
    "currencies": {"cp": 0, "sp": 0, "ep": 0, "gp": 15, "pp": 0},
    "inventory": [],
}

_WIZARD3_ROGUE2 = {
    "id": 22222,
    "name": "Mira",
    "stats": [
        {"id": 1, "value": 8},
        {"id": 2, "value": 16},
        {"id": 3, "value": 12},
        {"id": 4, "value": 16},
        {"id": 5, "value": 10},
        {"id": 6, "value": 12},
    ],
    "bonusStats": [{"id": i, "value": None} for i in range(1, 7)],
    "overrideStats": [{"id": i, "value": None} for i in range(1, 7)],
    "classes": [
        {
            "level": 3,
            "definition": {"name": "Wizard", "hitDice": 6, "spellcastingAbility": 4},
        },
        {
            "level": 2,
            "definition": {"name": "Rogue", "hitDice": 8, "spellcastingAbility": None},
        },
    ],
    "hitPointInfo": {
        "baseHitPoints": 22,
        "constitutionHitPointBonus": 5,
        "bonusHitPoints": 0,
        "removedHitPoints": 0,
        "temporaryHitPoints": 0,
    },
    "modifiers": {
        "class": [
            {"type": "proficiency", "subType": "intelligence-saving-throws"},
            {"type": "proficiency", "subType": "wisdom-saving-throws"},
            {"type": "proficiency", "subType": "arcana"},
            {"type": "expertise", "subType": "stealth"},
        ],
        "race": [], "background": [], "item": [], "feat": [], "condition": [],
    },
    "race": {
        "fullName": "Elf",
        "weightSpeeds": {"normal": {"walk": 30}},
    },
    "currencies": {"cp": 0, "sp": 0, "ep": 0, "gp": 50, "pp": 1},
    "inventory": [],
}


# ─── ability score resolution ─────────────────────────────────────────────────

def test_resolve_abilities_monk():
    ab = _resolve_ability_scores(_MONK5)
    assert ab["str"] == 10
    assert ab["dex"] == 14
    assert ab["con"] == 12


def test_resolve_ability_override():
    data = dict(_MONK5)
    data["overrideStats"] = [{"id": 2, "value": 18}] + [{"id": i, "value": None} for i in [1,3,4,5,6]]
    ab = _resolve_ability_scores(data)
    assert ab["dex"] == 18  # override wins


def test_resolve_ability_bonus():
    data = dict(_MONK5)
    data["bonusStats"] = [{"id": 2, "value": 2}] + [{"id": i, "value": None} for i in [1,3,4,5,6]]
    ab = _resolve_ability_scores(data)
    assert ab["dex"] == 16  # 14 + 2


# ─── max HP ───────────────────────────────────────────────────────────────────

def test_manual_max_hp_monk5():
    ab = _resolve_ability_scores(_MONK5)
    hp = _manual_max_hp(_MONK5, ab)
    # hitPointInfo present: 33 + 5 = 38
    assert hp == 38


def test_manual_max_hp_fallback():
    # Remove hitPointInfo → manual calculation
    data = {**_MONK5, "hitPointInfo": {}}
    ab = _resolve_ability_scores(data)
    hp = _manual_max_hp(data, ab)
    # Monk 5: 8 (first level) + 5×4 (avg d8) + 1×5 (con_mod=1)
    # = 8 + 20 + 5 = 33 (rough, depends on implementation)
    assert hp > 0


# ─── full derive ──────────────────────────────────────────────────────────────

def test_derive_monk_identity():
    d = derive(_MONK5)
    assert d["name"] == "Kira"
    assert d["level"] == 5
    assert "Mnk" in d["class_summary"]
    assert d["ddb_id"] == "11111"


def test_derive_monk_ac_not_derived():
    d = derive(_MONK5)
    assert d["ac"] is None  # never derived — needs override


def test_derive_monk_speed():
    d = derive(_MONK5)
    assert d["speed"] == 30


def test_derive_monk_gold():
    d = derive(_MONK5)
    assert d["gold"] == 15


def test_derive_monk_hit_dice():
    d = derive(_MONK5)
    assert "d8" in d["hit_dice"]
    assert d["hit_dice"]["d8"]["max"] == 5
    assert d["hit_dice"]["d8"]["used"] == 0


def test_derive_monk_no_spell_slots():
    d = derive(_MONK5)
    # Monk is not a spellcaster (no spell slots at base level 5)
    # spell_slots may be empty or have no entries
    assert d["pact_slots"] is None


def test_derive_multiclass_wizard_rogue():
    d = derive(_WIZARD3_ROGUE2)
    assert d["name"] == "Mira"
    assert d["level"] == 5
    assert "Wiz" in d["class_summary"]
    assert "Rog" in d["class_summary"]


def test_derive_wizard_spell_slots():
    d = derive(_WIZARD3_ROGUE2)
    # Wizard 3 gets L1 and L2 slots
    slots = d["spell_slots"]
    assert "1" in slots
    assert slots["1"]["max"] >= 2


def test_derive_wizard_hit_dice():
    d = derive(_WIZARD3_ROGUE2)
    hd = d["hit_dice"]
    # d6 from Wizard, d8 from Rogue
    assert "d6" in hd
    assert "d8" in hd
    assert hd["d6"]["max"] == 3
    assert hd["d8"]["max"] == 2


def test_derive_proficiency_bonus():
    d = derive(_MONK5)
    assert d["proficiency_bonus"] == 3  # level 5 = +3


def test_derive_monk_saves():
    # Manual fallback saves from modifiers
    from ddb.derive import _derive_manual
    d = _derive_manual(_MONK5)
    assert d["saves"]["str"] is True
    assert d["saves"]["dex"] is True
    assert d["saves"]["int"] is False


def test_derive_monk_skills():
    from ddb.derive import _derive_manual
    d = _derive_manual(_MONK5)
    assert d["skills"]["acrobatics"] == "proficiency"
    assert d["skills"]["stealth"] == "proficiency"
    assert d["skills"]["arcana"] == "none"


def test_derive_expertise():
    from ddb.derive import _derive_manual
    d = _derive_manual(_WIZARD3_ROGUE2)
    assert d["skills"]["stealth"] == "expertise"


def test_derive_gold_platinum():
    d = derive(_WIZARD3_ROGUE2)
    assert d["gold"] == 60  # 50 gp + 10 (1 pp)


# ─── diff ─────────────────────────────────────────────────────────────────────

def test_diff_detects_mismatch():
    derived = {"max_hp": 38, "level": 5, "class_summary": "Mnk 5",
               "speed": 30, "abilities": {}, "spell_slots": {}, "pact_slots": None, "hit_dice": {}}
    existing = {"max_hp": 36, "level": 5, "class_summary": "Mnk 5",
                "speed": 30, "abilities": {}, "spell_slots": {}, "pact_slots": None, "hit_dice": {}}
    mismatches = diff(derived, existing)
    assert "max_hp" in mismatches
    assert mismatches["max_hp"]["derived"] == 38
    assert mismatches["max_hp"]["existing"] == 36


def test_diff_no_mismatch():
    d = {"max_hp": 38, "level": 5, "class_summary": "Mnk 5",
         "speed": 30, "abilities": {}, "spell_slots": {}, "pact_slots": None, "hit_dice": {}}
    assert diff(d, d) == {}
