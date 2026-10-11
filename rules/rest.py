"""Rest recovery (SPEC §3 rest). Pure — operates on a character-shaped dict."""

from __future__ import annotations

from copy import deepcopy
from typing import Literal

Edition = Literal["2014", "2024"]
Kind = Literal["short", "long"]


def short_rest(char: dict) -> dict:
    """Restores:
    - resources with recharge == "short"
    - Pact Magic slots (always)
    Hit-die healing is a separate caller-driven step (roll + heal).
    """
    c = deepcopy(char)
    for key, res in c.get("resources", {}).items():
        if res.get("recharge") == "short":
            res["used"] = 0
    pact = c.get("pact_slots")
    if pact:
        pact["used"] = 0
    return c


def long_rest(char: dict, *, edition: Edition = "2014") -> dict:
    """Restores:
    - HP to max; temp_hp cleared
    - all spell slots and pact slots
    - resources with recharge in {"short","long"}; "dawn" resources also restore
    - death save counters cleared, stable=false
    - exhaustion −1 (floor 0)
    - hit dice: 2014 → half of max (min 1) per die type; 2024 → all

    "none" recharge resources are untouched.
    """
    c = deepcopy(char)
    c["hp"] = c["max_hp"]
    c["temp_hp"] = 0
    for slot in c.get("spell_slots", {}).values():
        slot["used"] = 0
    pact = c.get("pact_slots")
    if pact:
        pact["used"] = 0
    for res in c.get("resources", {}).values():
        if res.get("recharge") in ("short", "long", "dawn"):
            res["used"] = 0
    c["death_saves"] = {"successes": 0, "failures": 0}
    c["stable"] = False
    c["exhaustion"] = max(0, c.get("exhaustion", 0) - 1)

    hd = c.get("hit_dice", {})
    for die_key, pool in hd.items():
        max_dice = pool.get("max", 0)
        used = pool.get("used", 0)
        if edition == "2024":
            pool["used"] = 0
        else:
            # 2014: restore half of max (min 1)
            restored = max(1, max_dice // 2)
            pool["used"] = max(0, used - restored)
    return c
