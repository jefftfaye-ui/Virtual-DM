"""Initiative sort, tiebreak, turn skipping, effect ticking (SPEC §3 next_turn)."""

from __future__ import annotations

from dataclasses import dataclass
from secrets import SystemRandom

_RNG = SystemRandom()


@dataclass
class CombatantView:
    id: str
    name: str
    kind: str                # pc | monster | npc
    initiative: int
    dex_mod: int
    tiebreak: int | None
    status: str              # active | down | dead | fled | removed
    hp: int
    stable: bool = False


def sort_initiative(combatants: list[CombatantView]) -> list[CombatantView]:
    """Sort: initiative desc, dex_mod desc, tiebreak desc. None initiative sinks to the end."""
    def key(c: CombatantView) -> tuple:
        # None initiative treated as -inf for sort purposes
        init = c.initiative if c.initiative is not None else -(10**9)
        tb = c.tiebreak if c.tiebreak is not None else 0
        return (-init, -c.dex_mod, -tb, c.name)
    return sorted(combatants, key=key)


def assign_tiebreaks(combatants: list[CombatantView]) -> list[CombatantView]:
    """For any (initiative, dex_mod) collision missing tiebreak, roll one.
    Caller is responsible for persisting the result.
    """
    groups: dict[tuple[int, int], list[CombatantView]] = {}
    for c in combatants:
        if c.initiative is None:
            continue
        groups.setdefault((c.initiative, c.dex_mod), []).append(c)
    for group in groups.values():
        if len(group) < 2:
            continue
        for c in group:
            if c.tiebreak is None:
                c.tiebreak = _RNG.randint(1, 10_000)
    return combatants


def is_skippable(c: CombatantView) -> bool:
    """next_turn skips dead/fled/removed/down. PCs at 0 HP still get a turn
    (for the death-save prompt) unless stable or dead.
    """
    if c.status in ("dead", "fled", "removed"):
        return True
    if c.kind in ("monster", "npc") and c.status == "down":
        return True
    if c.kind == "pc" and c.hp == 0 and (c.stable or c.status == "dead"):
        return True
    return False


def next_index(combatants: list[CombatantView], current_index: int) -> tuple[int, int]:
    """Return (new_index, rounds_advanced). Advances through skippable combatants."""
    n = len(combatants)
    if n == 0:
        raise ValueError("no combatants")
    rounds_advanced = 0
    idx = current_index
    for _ in range(n + 1):
        idx += 1
        if idx >= n:
            idx = 0
            rounds_advanced += 1
        if not is_skippable(combatants[idx]):
            return idx, rounds_advanced
    # entire turn order is skippable
    raise ValueError("no active combatants")
