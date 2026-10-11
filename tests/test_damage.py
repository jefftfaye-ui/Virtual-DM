"""Tests for damage pipeline — SPEC §7 acceptance item 2."""

from __future__ import annotations

import pytest

from rules.damage import DamageInput, TargetState, apply_damage, apply_heal


def mk(hp=20, max_hp=20, temp=0, **kw) -> TargetState:
    return TargetState(hp=hp, max_hp=max_hp, temp_hp=temp, **kw)


def test_resistance_halves_round_down() -> None:
    out = apply_damage(mk(resistances=["fire"]), DamageInput(amount=7, type="fire"))
    assert out.resisted
    assert out.hp_after == 20 - 3  # 7 // 2 = 3


def test_immunity_zeroes() -> None:
    out = apply_damage(mk(immunities=["poison"]), DamageInput(amount=15, type="poison"))
    assert out.immune
    assert out.hp_after == 20


def test_vulnerability_doubles() -> None:
    out = apply_damage(mk(vulnerabilities=["cold"]), DamageInput(amount=4, type="cold"))
    assert out.vulnerable
    assert out.hp_after == 20 - 8


def test_resistance_applied_before_temp_hp() -> None:
    out = apply_damage(
        mk(temp=4, resistances=["fire"]),
        DamageInput(amount=10, type="fire"),
    )
    # 10 resisted → 5. temp absorbs 4. HP takes 1.
    assert out.applied == 5
    assert out.temp_absorbed == 4
    assert out.temp_hp_after == 0
    assert out.hp_after == 19


def test_temp_hp_absorbs_first_fully() -> None:
    out = apply_damage(mk(temp=20), DamageInput(amount=15, type="slashing"))
    assert out.temp_absorbed == 15
    assert out.temp_hp_after == 5
    assert out.hp_after == 20


def test_hp_clamps_at_zero() -> None:
    out = apply_damage(mk(hp=5), DamageInput(amount=99, type="slashing"))
    assert out.hp_after == 0
    assert out.dropped


def test_massive_damage_kills() -> None:
    # Full HP 20, hit for 50: brings to 0 + 30 overflow ≥ max_hp 20 → dead.
    out = apply_damage(mk(hp=20, max_hp=20), DamageInput(amount=50, type="force"))
    assert out.dead


def test_massive_damage_disabled_does_not_kill() -> None:
    out = apply_damage(
        mk(hp=20, max_hp=20),
        DamageInput(amount=50, type="force"),
        massive_damage_enabled=False,
    )
    assert not out.dead
    assert out.hp_after == 0
    assert out.dropped


def test_damage_at_zero_adds_one_failure() -> None:
    out = apply_damage(mk(hp=0, max_hp=20), DamageInput(amount=3, type="slashing"))
    assert out.death_failures_added == 1
    assert not out.dead


def test_damage_at_zero_crit_adds_two_failures() -> None:
    out = apply_damage(
        mk(hp=0, max_hp=20),
        DamageInput(amount=3, type="slashing", crit=True),
    )
    assert out.death_failures_added == 2


def test_single_hit_at_or_above_max_at_zero_kills() -> None:
    out = apply_damage(mk(hp=0, max_hp=20), DamageInput(amount=20, type="slashing"))
    assert out.dead


def test_concentration_check_dc_is_max_10_half_damage() -> None:
    out = apply_damage(
        mk(hp=30, max_hp=30, concentrating=True),
        DamageInput(amount=14, type="fire"),
    )
    assert out.concentration_check == {"dc": 10}  # 14/2 = 7, min 10

    out = apply_damage(
        mk(hp=50, max_hp=50, concentrating=True),
        DamageInput(amount=40, type="fire"),
    )
    assert out.concentration_check == {"dc": 20}


def test_concentration_dc_capped_at_30_in_2024() -> None:
    out = apply_damage(
        mk(hp=100, max_hp=100, concentrating=True),
        DamageInput(amount=80, type="force"),
        edition="2024",
    )
    assert out.concentration_check == {"dc": 30}


def test_concentration_ends_on_drop_to_zero() -> None:
    out = apply_damage(
        mk(hp=5, max_hp=20, concentrating=True),
        DamageInput(amount=10, type="slashing"),
    )
    assert out.dropped
    assert out.ended_concentration
    assert out.concentration_check is None  # unconscious — no check


def test_healing_clears_death_saves_and_stable() -> None:
    t = mk(hp=0, death_successes=2, death_failures=1, stable=True)
    apply_heal(t, 5)
    assert t.hp == 5
    assert t.death_successes == 0
    assert t.death_failures == 0
    assert not t.stable


def test_healing_clamps_to_max() -> None:
    t = mk(hp=18, max_hp=20)
    apply_heal(t, 50)
    assert t.hp == 20


def test_dead_stays_dead() -> None:
    t = mk(hp=0, dead=True)
    apply_heal(t, 10)
    assert t.hp == 0
    assert t.dead


def test_zero_damage_no_concentration_check() -> None:
    out = apply_damage(
        mk(hp=20, concentrating=True, immunities=["cold"]),
        DamageInput(amount=10, type="cold"),
    )
    assert out.concentration_check is None  # immune → applied == 0
