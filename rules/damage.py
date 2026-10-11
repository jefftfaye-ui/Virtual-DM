"""Damage pipeline (SPEC §3 update_character). Pure, no DB."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Edition = Literal["2014", "2024"]


@dataclass
class DamageInput:
    amount: int
    type: str = "untyped"
    crit: bool = False


@dataclass
class TargetState:
    hp: int
    max_hp: int
    temp_hp: int = 0
    resistances: list[str] = field(default_factory=list)
    immunities: list[str] = field(default_factory=list)
    vulnerabilities: list[str] = field(default_factory=list)
    concentrating: bool = False
    stable: bool = False
    dead: bool = False
    death_successes: int = 0
    death_failures: int = 0


@dataclass
class DamageOutcome:
    hp_after: int
    temp_hp_after: int
    temp_absorbed: int = 0
    applied: int = 0  # after resist/vuln/immune, before temp/HP absorption
    immune: bool = False
    resisted: bool = False
    vulnerable: bool = False
    dropped: bool = False  # went from >0 to 0
    dead: bool = False
    concentration_check: dict | None = None  # {"dc": int}
    ended_concentration: bool = False
    death_failures_added: int = 0


def _match(type_: str, bucket: list[str]) -> bool:
    t = (type_ or "").lower().strip()
    return any(t == b.lower().strip() for b in bucket)


def apply_damage(
    target: TargetState,
    dmg: DamageInput,
    *,
    edition: Edition = "2014",
    massive_damage_enabled: bool = True,
) -> DamageOutcome:
    """Apply damage per SPEC §3 pipeline.

    Order: immunity → resist/vuln → temp_hp absorbs → hp.
    Then: dropped-to-0 effects, death-save failures while at 0, massive damage,
    concentration check if still up.
    """
    if dmg.amount < 0:
        raise ValueError("damage amount must be >= 0")

    out = DamageOutcome(hp_after=target.hp, temp_hp_after=target.temp_hp)

    # already dead: no change
    if target.dead:
        out.dead = True
        return out

    # 1. type modifiers
    amount = dmg.amount
    if _match(dmg.type, target.immunities):
        out.immune = True
        amount = 0
    else:
        if _match(dmg.type, target.resistances):
            amount = amount // 2
            out.resisted = True
        if _match(dmg.type, target.vulnerabilities):
            amount = amount * 2
            out.vulnerable = True
    out.applied = amount

    # 2. temp HP absorbs first
    if amount > 0 and target.temp_hp > 0:
        absorbed = min(target.temp_hp, amount)
        out.temp_absorbed = absorbed
        out.temp_hp_after = target.temp_hp - absorbed
        amount -= absorbed

    # 3. HP
    if amount > 0:
        new_hp = max(0, target.hp - amount)
    else:
        new_hp = target.hp
    out.hp_after = new_hp

    was_up = target.hp > 0
    at_zero = new_hp == 0

    # 4. death / downed logic
    if was_up and at_zero:
        out.dropped = True
        if target.concentrating:
            out.ended_concentration = True

        # massive damage: leftover ≥ max_hp kills outright
        if massive_damage_enabled:
            # "leftover damage" = damage past bringing HP to 0
            overflow = max(0, amount - target.hp)
            if overflow >= target.max_hp:
                out.dead = True
                return out

    elif not was_up and amount > 0:
        # already at 0, taking damage
        # instant kill if single hit >= max_hp
        if amount >= target.max_hp:
            out.dead = True
            return out
        fails = 2 if dmg.crit else 1
        out.death_failures_added = fails
        # (caller writes failures back; cap handled at death_save layer)

    # 5. concentration check if still conscious and was concentrating
    if target.concentrating and new_hp > 0 and out.applied > 0:
        dc = max(10, out.applied // 2)
        if edition == "2024":
            dc = min(dc, 30)
        out.concentration_check = {"dc": dc}

    return out


def apply_heal(target: TargetState, amount: int) -> TargetState:
    """Clamp to max; any healing above 0 clears death saves + stable + dead(false only if alive)."""
    if amount < 0:
        raise ValueError("heal amount must be >= 0")
    if target.dead:
        # dead stays dead unless revived explicitly elsewhere
        return target
    new_hp = min(target.max_hp, target.hp + amount)
    if new_hp > 0:
        target.death_successes = 0
        target.death_failures = 0
        target.stable = False
    target.hp = new_hp
    return target
