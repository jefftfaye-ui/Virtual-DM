"""Property + unit tests for dice parser and roller.

Covers SPEC §7 acceptance item 1:
- bounds hold across 10k rolls
- kh/kl respected
- advantage/disadvantage picks correct d20
- bad notation rejected
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from dice.parser import DiceError, parse, roll, ALLOWED_SIDES


# ─── parsing ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expr",
    [
        "1d20",
        "d20",
        "20",
        "1d20+5",
        "2d6+1d4+3",
        "4d6kh3",
        "4d6kl1",
        "1d20-1",
        "-1d4+2",
        "1d6 + 2",
        "1D20+5",  # case insensitive
    ],
)
def test_parse_accepts_valid(expr: str) -> None:
    parse(expr)


@pytest.mark.parametrize(
    "expr",
    [
        "",
        "   ",
        "1d7",       # not a standard die
        "1d20++5",
        "1d20 5",    # missing operator
        "1d20kh",    # keep without count
        "5d20kh6",   # keep more than rolled
        "0d20",      # count must be >= 1
        "abc",
        "1d20 + abc",
        "+",
        "1d20 +",
        "101d6",     # count ceiling
    ],
)
def test_parse_rejects_invalid(expr: str) -> None:
    with pytest.raises(DiceError):
        parse(expr)


# ─── bounds across many rolls ──────────────────────────────────────────


@settings(max_examples=200, deadline=None)
@given(
    count=st.integers(min_value=1, max_value=10),
    sides=st.sampled_from(sorted(ALLOWED_SIDES)),
    mod=st.integers(min_value=-20, max_value=20),
)
def test_roll_within_bounds(count: int, sides: int, mod: int) -> None:
    expr = f"{count}d{sides}{'+' if mod >= 0 else ''}{mod}"
    for _ in range(50):  # 200 * 50 = 10k
        r = roll(expr)
        assert len(r.dice) == count
        for d in r.dice:
            assert 1 <= d <= sides
        assert r.total == sum(r.dice) + mod


def test_many_rolls_full_range_coverage() -> None:
    seen = set()
    for _ in range(2000):
        seen.add(roll("1d20").total)
    assert seen == set(range(1, 21))


# ─── keep high / keep low ──────────────────────────────────────────────


def test_kh_keeps_highest() -> None:
    for _ in range(500):
        r = roll("4d6kh3")
        assert len(r.dice) == 4
        assert len(r.kept) == 3
        assert sorted(r.kept, reverse=True) == sorted(r.dice, reverse=True)[:3]
        assert r.total == sum(r.kept)


def test_kl_keeps_lowest() -> None:
    for _ in range(500):
        r = roll("4d6kl1")
        assert len(r.kept) == 1
        assert r.kept[0] == min(r.dice)


# ─── advantage / disadvantage ──────────────────────────────────────────


def test_advantage_picks_higher_of_two_d20() -> None:
    for _ in range(500):
        r = roll("1d20+5", mode="advantage")
        assert len(r.dice) == 2
        assert r.natural == max(r.dice)
        assert r.total == max(r.dice) + 5
        assert r.mode == "advantage"


def test_disadvantage_picks_lower() -> None:
    for _ in range(500):
        r = roll("1d20", mode="disadvantage")
        assert len(r.dice) == 2
        assert r.natural == min(r.dice)
        assert r.total == min(r.dice)


def test_advantage_ignored_when_no_d20() -> None:
    r = roll("2d6+3", mode="advantage")
    assert r.mode == "normal"
    assert len(r.dice) == 2


def test_advantage_rejects_multi_d20() -> None:
    with pytest.raises(DiceError):
        roll("2d20+5", mode="advantage")


# ─── natural d20 reported ──────────────────────────────────────────────


def test_natural_reported_for_single_d20() -> None:
    for _ in range(50):
        r = roll("1d20+5")
        assert r.natural == r.dice[0]


def test_natural_none_when_no_single_d20() -> None:
    r = roll("2d6+3")
    assert r.natural is None


# ─── mixed terms ────────────────────────────────────────────────────────


def test_mixed_terms_sum_correctly() -> None:
    for _ in range(200):
        r = roll("2d6+1d4+3")
        assert len(r.dice) == 3
        assert r.modifier == 3
        assert r.total == sum(r.dice) + 3


def test_negative_mod() -> None:
    r = roll("1d20-1")
    assert r.total == r.dice[0] - 1


def test_leading_negative() -> None:
    r = roll("-1d4+5")
    assert r.total == -r.dice[0] + 5
