"""Exhaustion effects per edition. Returns the human-readable description."""

from __future__ import annotations

from typing import Literal

Edition = Literal["2014", "2024"]

_2014 = {
    0: "none",
    1: "disadvantage on ability checks",
    2: "speed halved",
    3: "disadvantage on attack rolls and saving throws",
    4: "hit point maximum halved",
    5: "speed reduced to 0",
    6: "death",
}

# 2024: cumulative −2 per level on d20 Tests, −2× level to spell save DCs, death at 10.
def describe(level: int, *, edition: Edition = "2014") -> str:
    if level < 0:
        raise ValueError("exhaustion cannot be negative")
    if edition == "2014":
        return _2014.get(min(level, 6), _2014[6])
    # 2024
    if level >= 10:
        return "death"
    penalty = -2 * level
    return f"{penalty} to d20 Tests; spell save DCs reduced by {abs(penalty)}"


def modifier_2024(level: int) -> int:
    """2024 d20-Test penalty (negative integer)."""
    return -2 * max(0, min(level, 10))
