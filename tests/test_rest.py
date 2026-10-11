from rules.rest import short_rest, long_rest


BASE = {
    "max_hp": 30, "hp": 10, "temp_hp": 4,
    "exhaustion": 2, "stable": True,
    "death_saves": {"successes": 1, "failures": 2},
    "spell_slots": {"1": {"max": 4, "used": 3}, "2": {"max": 2, "used": 2}},
    "pact_slots": {"level": 3, "max": 2, "used": 2},
    "resources": {
        "ki":        {"max": 5, "used": 3, "recharge": "short"},
        "channel":   {"max": 1, "used": 1, "recharge": "short"},
        "wild":      {"max": 1, "used": 1, "recharge": "long"},
        "dawn_item": {"max": 1, "used": 1, "recharge": "dawn"},
        "never":     {"max": 1, "used": 1, "recharge": "none"},
    },
    "hit_dice": {"d8": {"max": 5, "used": 4}, "d10": {"max": 2, "used": 2}},
}


def test_short_rest_restores_short_resources_and_pact_only():
    c = short_rest(BASE)
    assert c["resources"]["ki"]["used"] == 0
    assert c["resources"]["channel"]["used"] == 0
    assert c["resources"]["wild"]["used"] == 1       # long: untouched
    assert c["resources"]["dawn_item"]["used"] == 1  # dawn: untouched
    assert c["pact_slots"]["used"] == 0
    assert c["spell_slots"]["1"]["used"] == 3        # spell slots untouched
    assert c["hp"] == 10                              # no auto-heal


def test_long_rest_2014_restores_half_hit_dice():
    c = long_rest(BASE, edition="2014")
    assert c["hp"] == 30
    assert c["temp_hp"] == 0
    for s in c["spell_slots"].values():
        assert s["used"] == 0
    assert c["pact_slots"]["used"] == 0
    # d8: max 5, used 4, restore max(1, 5//2)=2 → used = 2
    assert c["hit_dice"]["d8"]["used"] == 2
    # d10: max 2, used 2, restore max(1,1)=1 → used = 1
    assert c["hit_dice"]["d10"]["used"] == 1
    assert c["death_saves"] == {"successes": 0, "failures": 0}
    assert c["stable"] is False
    assert c["exhaustion"] == 1
    assert c["resources"]["dawn_item"]["used"] == 0
    assert c["resources"]["never"]["used"] == 1


def test_long_rest_2024_restores_all_hit_dice():
    c = long_rest(BASE, edition="2024")
    assert c["hit_dice"]["d8"]["used"] == 0
    assert c["hit_dice"]["d10"]["used"] == 0


def test_long_rest_exhaustion_floor_zero():
    base = {**BASE, "exhaustion": 0}
    c = long_rest(base)
    assert c["exhaustion"] == 0
