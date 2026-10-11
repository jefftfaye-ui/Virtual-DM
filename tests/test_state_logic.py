"""Unit tests for pure logic in tools/state.py — no DB needed.

Tests: slot/resource/hit-die overspend refusal, condition merge, _char_to_target shape.
"""

from __future__ import annotations

import pytest

from tools.state import (
    _apply_conditions,
    _slot_use,
    _pact_use,
    _resource_use,
    _hit_die_spend,
    _char_to_target,
)
from rules.damage import TargetState


# ─── conditions ───────────────────────────────────────────────────────────────


def test_conditions_add():
    assert _apply_conditions([], ["Poisoned", "BLINDED"], None) == ["blinded", "poisoned"]


def test_conditions_remove():
    assert _apply_conditions(["poisoned", "blinded"], None, ["Blinded"]) == ["poisoned"]


def test_conditions_dedup():
    assert _apply_conditions(["poisoned"], ["POISONED"], None) == ["poisoned"]


def test_conditions_add_and_remove():
    result = _apply_conditions(["blinded"], ["frightened"], ["blinded"])
    assert result == ["frightened"]


# ─── spell slots ──────────────────────────────────────────────────────────────


def test_slot_use_ok():
    slots = {"1": {"max": 4, "used": 0}, "2": {"max": 2, "used": 1}}
    result = _slot_use(slots, "1", restore=False)
    assert not isinstance(result, str)
    assert result["1"]["used"] == 1


def test_slot_use_overspend():
    slots = {"1": {"max": 2, "used": 2}}
    result = _slot_use(slots, "1", restore=False)
    assert isinstance(result, str)
    assert "no level-1 slots" in result


def test_slot_restore():
    slots = {"1": {"max": 4, "used": 2}}
    result = _slot_use(slots, "1", restore=True)
    assert not isinstance(result, str)
    assert result["1"]["used"] == 1


def test_slot_restore_floor_zero():
    slots = {"1": {"max": 4, "used": 0}}
    result = _slot_use(slots, "1", restore=True)
    assert not isinstance(result, str)
    assert result["1"]["used"] == 0


def test_slot_unknown_level():
    result = _slot_use({}, "3", restore=False)
    assert isinstance(result, str)


# ─── pact slots ───────────────────────────────────────────────────────────────


def test_pact_use_ok():
    pact = {"level": 3, "max": 2, "used": 0}
    result = _pact_use(pact, restore=False)
    assert not isinstance(result, str)
    assert result["used"] == 1


def test_pact_use_exhausted():
    pact = {"level": 3, "max": 2, "used": 2}
    result = _pact_use(pact, restore=False)
    assert isinstance(result, str)
    assert "no pact slots" in result


def test_pact_use_none():
    result = _pact_use(None, restore=False)
    assert isinstance(result, str)
    assert "no Pact Magic" in result


# ─── resources ────────────────────────────────────────────────────────────────


def test_resource_use_ok():
    resources = {"ki": {"max": 5, "used": 0, "recharge": "short"}}
    result = _resource_use(resources, "ki", restore=False)
    assert not isinstance(result, str)
    assert result["ki"]["used"] == 1


def test_resource_use_exhausted():
    resources = {"ki": {"max": 5, "used": 5, "recharge": "short"}}
    result = _resource_use(resources, "ki", restore=False)
    assert isinstance(result, str)
    assert "ki" in result


def test_resource_unknown():
    result = _resource_use({}, "channel_divinity", restore=False)
    assert isinstance(result, str)
    assert "unknown" in result


# ─── hit dice ─────────────────────────────────────────────────────────────────


def test_hit_die_spend_ok():
    hd = {"d8": {"max": 5, "used": 2}}
    result = _hit_die_spend(hd, "d8", 2)
    assert not isinstance(result, str)
    assert result["d8"]["used"] == 4


def test_hit_die_overspend():
    hd = {"d8": {"max": 5, "used": 4}}
    result = _hit_die_spend(hd, "d8", 2)
    assert isinstance(result, str)
    assert "1 d8" in result


def test_hit_die_unknown():
    result = _hit_die_spend({}, "d12", 1)
    assert isinstance(result, str)


# ─── _char_to_target ──────────────────────────────────────────────────────────


def test_char_to_target_concentrating():
    t = _char_to_target({"hp": 20, "max_hp": 30, "temp_hp": 5,
                          "concentrating_on": "Bless", "stable": False, "dead": False,
                          "resistances": ["fire"], "immunities": [], "vulnerabilities": [],
                          "death_saves": {"successes": 0, "failures": 0}})
    assert isinstance(t, TargetState)
    assert t.concentrating
    assert t.resistances == ["fire"]
    assert t.hp == 20


def test_char_to_target_not_concentrating():
    t = _char_to_target({"hp": 0, "max_hp": 30, "temp_hp": 0,
                          "concentrating_on": None, "stable": True, "dead": False,
                          "resistances": [], "immunities": [], "vulnerabilities": [],
                          "death_saves": {"successes": 3, "failures": 0}})
    assert not t.concentrating
    assert t.stable
    assert t.death_successes == 3
