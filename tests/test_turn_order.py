from rules.turn_order import CombatantView, sort_initiative, is_skippable, next_index


def mk(**kw):
    defaults = dict(id="x", name="x", kind="pc", initiative=10, dex_mod=0,
                    tiebreak=None, status="active", hp=10, stable=False)
    defaults.update(kw)
    return CombatantView(**defaults)


def test_initiative_desc():
    a = mk(name="a", initiative=5)
    b = mk(name="b", initiative=18)
    c = mk(name="c", initiative=12)
    out = sort_initiative([a, b, c])
    assert [x.name for x in out] == ["b", "c", "a"]


def test_dex_tiebreak():
    a = mk(name="a", initiative=15, dex_mod=2)
    b = mk(name="b", initiative=15, dex_mod=5)
    out = sort_initiative([a, b])
    assert [x.name for x in out] == ["b", "a"]


def test_server_tiebreak():
    a = mk(name="a", initiative=15, dex_mod=3, tiebreak=5)
    b = mk(name="b", initiative=15, dex_mod=3, tiebreak=9)
    out = sort_initiative([a, b])
    assert [x.name for x in out] == ["b", "a"]


def test_none_initiative_sinks():
    a = mk(name="a", initiative=None)
    b = mk(name="b", initiative=1)
    out = sort_initiative([a, b])
    assert out[-1].name == "a"


def test_skip_dead_fled_removed():
    assert is_skippable(mk(status="dead"))
    assert is_skippable(mk(status="fled"))
    assert is_skippable(mk(status="removed"))


def test_skip_monster_down_not_pc_down():
    assert is_skippable(mk(kind="monster", status="down"))
    assert not is_skippable(mk(kind="pc", hp=0, stable=False))  # PC at 0 still gets turn


def test_pc_at_zero_stable_is_skipped():
    assert is_skippable(mk(kind="pc", hp=0, stable=True))


def test_next_index_wraps_and_counts_round():
    order = [mk(name="a", initiative=20), mk(name="b", initiative=10), mk(name="c", initiative=5)]
    i, rounds = next_index(order, 2)
    assert i == 0 and rounds == 1


def test_next_index_skips_dead():
    order = [
        mk(name="a", initiative=20),
        mk(name="b", initiative=15, status="dead"),
        mk(name="c", initiative=10),
    ]
    i, _ = next_index(order, 0)
    assert order[i].name == "c"
