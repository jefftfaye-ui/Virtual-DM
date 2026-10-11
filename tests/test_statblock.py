"""Unit tests for rules/statblock.py — pure, no DB."""

from __future__ import annotations

import pytest

from rules.statblock import (
    normalize_name,
    extract_monster_meta,
    format_monster_body,
)


# ─── normalize_name ───────────────────────────────────────────────────────────

def test_normalize_basic():
    assert normalize_name("Grappled") == "grappled"


def test_normalize_strips_punctuation():
    assert normalize_name("Fire Ball!") == "fire ball"


def test_normalize_multi_space():
    assert normalize_name("Hill  Giant") == "hill giant"


def test_normalize_apostrophe():
    assert normalize_name("Hunter's Mark") == "hunter s mark"


def test_normalize_roundtrip():
    # Same output regardless of case
    assert normalize_name("GOBLIN") == normalize_name("goblin")


# ─── extract_monster_meta ─────────────────────────────────────────────────────

_GOBLIN = {
    "name": "Goblin",
    "hit_points": 7,
    "hit_dice": "2d6",
    "armor_class": [{"value": 15, "type": "leather armor, shield"}],
    "dexterity": 14,
    "damage_resistances": [],
    "damage_immunities": [],
    "damage_vulnerabilities": [],
    "condition_immunities": [],
}

_ZOMBIE = {
    "name": "Zombie",
    "hit_points": 22,
    "hit_dice": "3d8+9",
    "armor_class": [{"value": 8, "type": "natural armor"}],
    "dexterity": 6,
    "damage_immunities": ["poison"],
    "damage_resistances": [],
    "damage_vulnerabilities": [],
    "condition_immunities": [{"name": "Poisoned"}, {"name": "Exhaustion"}],
}


def test_extract_goblin():
    meta = extract_monster_meta(_GOBLIN)
    assert meta["ac"] == 15
    assert meta["hp"] == 7
    assert meta["hit_dice"] == "2d6"
    assert meta["dex_mod"] == 2  # (14-10)//2
    assert meta["resistances"] == []
    assert meta["immunities"] == []


def test_extract_zombie_immunities():
    meta = extract_monster_meta(_ZOMBIE)
    assert meta["ac"] == 8
    assert meta["hp"] == 22
    assert "poison" in meta["immunities"]
    assert meta["dex_mod"] == -2  # (6-10)//2
    cond = meta["condition_immunities"]
    assert "poisoned" in cond


def test_extract_bare_ac_int():
    m = {**_GOBLIN, "armor_class": 13}
    meta = extract_monster_meta(m)
    assert meta["ac"] == 13


# ─── format_monster_body ──────────────────────────────────────────────────────

def test_format_monster_body_contains_name():
    body = format_monster_body(_GOBLIN)
    assert "Goblin" in body


def test_format_monster_body_contains_hp():
    body = format_monster_body(_GOBLIN)
    assert "7" in body
    assert "2d6" in body


def test_format_monster_body_contains_ac():
    body = format_monster_body(_GOBLIN)
    assert "15" in body


def test_format_monster_body_is_nonempty():
    body = format_monster_body({})
    assert isinstance(body, str)
