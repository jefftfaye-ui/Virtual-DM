"""Dice notation parser and roller.

Grammar (strict — anything else is rejected):

    expression := term (('+'|'-') term)*
    term       := dice | integer
    dice       := [count]'d'sides[keep]
    keep       := ('kh'|'kl') integer
    count      := integer >= 1 (default 1)
    sides      := integer in {2,3,4,6,8,10,12,20,100}
    integer    := [0-9]+

Examples: 1d20+5, 2d6+1d4+3, 4d6kh3, 1d20-1, d20, 20

RNG is secrets.SystemRandom — never seeded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from secrets import SystemRandom
from typing import Literal

_RNG = SystemRandom()

ALLOWED_SIDES = {2, 3, 4, 6, 8, 10, 12, 20, 100}
Mode = Literal["normal", "advantage", "disadvantage"]


class DiceError(ValueError):
    """Raised for any malformed or disallowed dice expression."""


@dataclass
class DieTerm:
    count: int
    sides: int
    keep: tuple[Literal["kh", "kl"], int] | None = None  # (mode, n)
    sign: int = 1  # +1 or -1

    def __post_init__(self) -> None:
        if self.count < 1 or self.count > 100:
            raise DiceError(f"die count must be 1..100, got {self.count}")
        if self.sides not in ALLOWED_SIDES:
            raise DiceError(f"sides must be one of {sorted(ALLOWED_SIDES)}, got d{self.sides}")
        if self.keep is not None:
            mode, n = self.keep
            if mode not in ("kh", "kl"):
                raise DiceError(f"keep mode must be kh or kl, got {mode}")
            if n < 1 or n > self.count:
                raise DiceError(f"keep count {n} out of range for {self.count} dice")


@dataclass
class ConstTerm:
    value: int
    sign: int = 1


Term = DieTerm | ConstTerm


@dataclass
class Expression:
    terms: list[Term]

    @property
    def modifier(self) -> int:
        return sum(t.sign * t.value for t in self.terms if isinstance(t, ConstTerm))


@dataclass
class RollResult:
    expression: str
    mode: Mode
    terms: list[dict]  # per-term detail for the event log
    dice: list[int]  # flat list of every die rolled (post-mode for d20)
    kept: list[int]  # dice that counted toward total
    modifier: int
    total: int
    natural: int | None = None  # d20 natural (post-mode) if a single d20 is present


# ─── parsing ────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"""
    \s*
    (?P<sign>[+-])?
    \s*
    (?:
        (?P<count>\d*)d(?P<sides>\d+)(?:(?P<keep>kh|kl)(?P<keepn>\d+))?
      |
        (?P<const>\d+)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def parse(expression: str) -> Expression:
    if not expression or not expression.strip():
        raise DiceError("empty expression")
    s = expression.strip().lower()
    # strip surrounding whitespace, then walk tokens left-to-right
    terms: list[Term] = []
    pos = 0
    first = True
    while pos < len(s):
        m = _TOKEN_RE.match(s, pos)
        if not m or m.end() == pos:
            raise DiceError(f"unparseable at position {pos}: {expression!r}")
        sign_tok = m.group("sign")
        if first and sign_tok is None:
            sign = 1
        elif first and sign_tok is not None:
            # leading '-' allowed, leading '+' allowed
            sign = -1 if sign_tok == "-" else 1
        else:
            if sign_tok is None:
                raise DiceError(f"missing operator before position {pos} in {expression!r}")
            sign = -1 if sign_tok == "-" else 1

        if m.group("const") is not None:
            terms.append(ConstTerm(value=int(m.group("const")), sign=sign))
        else:
            count_s = m.group("count")
            count = int(count_s) if count_s else 1
            sides = int(m.group("sides"))
            keep = None
            if m.group("keep"):
                keep = (m.group("keep"), int(m.group("keepn")))
            terms.append(DieTerm(count=count, sides=sides, keep=keep, sign=sign))

        pos = m.end()
        first = False
        # consume trailing whitespace
        while pos < len(s) and s[pos].isspace():
            pos += 1

    if not terms:
        raise DiceError(f"no terms in {expression!r}")
    return Expression(terms=terms)


# ─── rolling ────────────────────────────────────────────────────────────


def _roll_die(sides: int) -> int:
    return _RNG.randint(1, sides)


def _apply_keep(rolls: list[int], keep: tuple[str, int] | None) -> list[int]:
    if keep is None:
        return list(rolls)
    mode, n = keep
    ordered = sorted(rolls, reverse=(mode == "kh"))
    return ordered[:n]


def roll(expression: str, mode: Mode = "normal") -> RollResult:
    """Roll an expression. `mode` affects only the single d20 if present.

    Advantage/disadvantage with a d20 term: roll two d20s, pick higher/lower.
    If mode != normal and no d20 term exists, mode is ignored (and reported as "normal").
    """
    expr = parse(expression)
    effective_mode: Mode = mode

    # locate first (and ideally only) d20 term for advantage/disadvantage
    d20_idx = next(
        (i for i, t in enumerate(expr.terms) if isinstance(t, DieTerm) and t.sides == 20),
        None,
    )
    if mode != "normal" and d20_idx is None:
        effective_mode = "normal"

    terms_detail: list[dict] = []
    dice_flat: list[int] = []
    kept_flat: list[int] = []
    total = 0
    natural: int | None = None

    for i, t in enumerate(expr.terms):
        if isinstance(t, ConstTerm):
            total += t.sign * t.value
            terms_detail.append({"kind": "const", "value": t.value, "sign": t.sign})
            continue

        # DieTerm
        if effective_mode != "normal" and i == d20_idx:
            # roll twice, pick per mode (apply to a single d20 only)
            if t.count != 1 or t.keep is not None:
                raise DiceError(
                    "advantage/disadvantage requires a single d20 with no keep modifier"
                )
            a, b = _roll_die(20), _roll_die(20)
            picked = max(a, b) if effective_mode == "advantage" else min(a, b)
            dice_flat.extend([a, b])
            kept_flat.append(picked)
            total += t.sign * picked
            natural = picked
            terms_detail.append(
                {
                    "kind": "die",
                    "sides": 20,
                    "count": 1,
                    "rolls": [a, b],
                    "kept": [picked],
                    "mode": effective_mode,
                    "sign": t.sign,
                }
            )
            continue

        rolls = [_roll_die(t.sides) for _ in range(t.count)]
        kept = _apply_keep(rolls, t.keep)
        dice_flat.extend(rolls)
        kept_flat.extend(kept)
        total += t.sign * sum(kept)
        if t.sides == 20 and t.count == 1 and t.keep is None and natural is None:
            natural = rolls[0]
        terms_detail.append(
            {
                "kind": "die",
                "sides": t.sides,
                "count": t.count,
                "rolls": rolls,
                "kept": kept,
                "keep": list(t.keep) if t.keep else None,
                "sign": t.sign,
            }
        )

    return RollResult(
        expression=expression,
        mode=effective_mode,
        terms=terms_detail,
        dice=dice_flat,
        kept=kept_flat,
        modifier=expr.modifier,
        total=total,
        natural=natural,
    )
