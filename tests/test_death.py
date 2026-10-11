from rules.death import resolve


def test_nat20_regains_hp_and_resets():
    o = resolve(20, successes=1, failures=2)
    assert o.regained_hp
    assert o.successes == 0 and o.failures == 0


def test_nat1_adds_two_failures():
    o = resolve(1, successes=0, failures=0)
    assert o.failures == 2
    assert not o.dead


def test_nat1_from_two_failures_kills():
    o = resolve(1, successes=0, failures=2)
    assert o.dead


def test_ten_or_higher_is_success():
    o = resolve(10, successes=0, failures=0)
    assert o.successes == 1


def test_below_ten_is_failure():
    o = resolve(9, successes=0, failures=0)
    assert o.failures == 1


def test_three_successes_stable():
    o = resolve(15, successes=2, failures=1)
    assert o.stable
    assert o.successes == 0 and o.failures == 0


def test_three_failures_dead():
    o = resolve(5, successes=1, failures=2)
    assert o.dead
