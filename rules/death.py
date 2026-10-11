"""Death save resolution (SPEC §3 death_save)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeathSaveOutcome:
    natural: int
    successes: int
    failures: int
    stable: bool = False
    dead: bool = False
    regained_hp: bool = False
    message: str = ""


def resolve(natural: int, *, successes: int, failures: int) -> DeathSaveOutcome:
    """Resolve a death save given the natural d20.

    - nat 20: regain 1 HP, conscious (counters reset)
    - nat 1: +2 failures
    - 10+: +1 success
    - <10: +1 failure
    Three successes → stable (counters reset). Three failures → dead.
    """
    if not (1 <= natural <= 20):
        raise ValueError("natural must be 1..20")

    out = DeathSaveOutcome(natural=natural, successes=successes, failures=failures)

    if natural == 20:
        out.successes = 0
        out.failures = 0
        out.regained_hp = True
        out.message = "nat 20: regain 1 HP"
        return out

    if natural == 1:
        out.failures = min(3, failures + 2)
    elif natural >= 10:
        out.successes = min(3, successes + 1)
    else:
        out.failures = min(3, failures + 1)

    if out.failures >= 3:
        out.dead = True
        out.message = "three failures — dead"
    elif out.successes >= 3:
        out.stable = True
        out.successes = 0
        out.failures = 0
        out.message = "three successes — stable"

    return out
