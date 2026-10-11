"""Integration tests for Phase 3 combat tools. Skipped without SUPABASE_URL.

Covers SPEC §7.3 scripted fight acceptance criteria:
1. 2 PCs vs 3 goblins, auto-named
2. Round-2 reinforcement added
3. One goblin flees
4. Initiative tie broken by dex then tiebreak
5. PC drops → death_save_due
6. 1-round effect expires on correct boundary
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from tests.conftest import DB_URL

skip = pytest.mark.skipif(not DB_URL, reason="SUPABASE_URL not set")

from tools.combat import (
    _start_encounter_impl,
    _add_combatant_impl,
    _update_combatant_impl,
    _next_turn_impl,
    _end_encounter_impl,
)
from tools.state import _get_state_impl
from db import repo

pytestmark = skip


# ─── fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def character_id2(conn, campaign_id):
    """Second PC: Rogue, 20 HP."""
    cur = await conn.execute(
        """
        INSERT INTO characters (
            campaign_id, player_name, name, level, class_summary, ac, max_hp, hp, temp_hp,
            speed, abilities, saves, skills, spell_slots, hit_dice, resources, death_saves,
            resistances, immunities, vulnerabilities, conditions, inventory
        ) VALUES (
            %s, 'Julee', 'Mira', 4, 'Rogue 4', 14, 20, 20, 0, 30,
            '{"str":8,"dex":16,"con":12,"int":14,"wis":10,"cha":12}'::jsonb,
            '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{"d8":{"max":4,"used":0}}'::jsonb,
            '{}'::jsonb, '{"successes":0,"failures":0}'::jsonb,
            '{}', '{}', '{}', '{}', '[]'::jsonb
        ) RETURNING id
        """,
        (campaign_id,),
    )
    row = await cur.fetchone()
    return str(row[0])


async def _start_3goblin_fight(conn, campaign_id, session_id, character_id, character_id2):
    """Helper: start encounter, add 2 PCs, return encounter_id + combatant IDs."""
    enc = await _start_encounter_impl(
        conn,
        "Goblin Ambush",
        [{"name": "Goblin", "count": 3, "ac": 15, "hp": 7, "dex_mod": 2}],
        "ambush",
        campaign_id, session_id, None,
    )
    assert "error" not in enc, enc
    encounter_id = enc["encounter_id"]
    goblin_ids = [c["id"] for c in enc["combatants"]]

    # Add 2 PCs
    pc1 = await _add_combatant_impl(
        conn, encounter_id, "pc", "Kira", "joins", campaign_id, session_id,
        ref_id=character_id, initiative=15,
    )
    pc2 = await _add_combatant_impl(
        conn, encounter_id, "pc", "Mira", "joins", campaign_id, session_id,
        ref_id=character_id2, initiative=12,
    )
    return encounter_id, goblin_ids, pc1["combatant_id"], pc2["combatant_id"]


# ─── P3.1 start_encounter ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_encounter_auto_names_goblins(conn, campaign_id, session_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 3, "ac": 15, "hp": 7, "dex_mod": 2}],
        "test", campaign_id, session_id, None,
    )
    assert "error" not in enc
    names = [c["name"] for c in enc["combatants"]]
    assert names == ["Goblin 1", "Goblin 2", "Goblin 3"]


@pytest.mark.asyncio
async def test_start_encounter_monsters_have_initiative(conn, campaign_id, session_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 2, "ac": 15, "hp": 7, "dex_mod": 2}],
        "test", campaign_id, session_id, None,
    )
    for c in enc["combatants"]:
        assert c["initiative"] is not None
        assert 3 <= c["initiative"] <= 22  # 1d20 + 2


@pytest.mark.asyncio
async def test_start_encounter_requires_ac_hp(conn, campaign_id, session_id):
    result = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 1}],
        "test", campaign_id, session_id, None,
    )
    assert "error" in result


# ─── P3.2 add_combatant ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_pc_combatant(conn, campaign_id, session_id, character_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 1, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    result = await _add_combatant_impl(
        conn, enc["encounter_id"], "pc", "Kira", "joins", campaign_id, session_id,
        ref_id=character_id,
    )
    assert "error" not in result
    assert result["kind"] == "pc"
    assert result["initiative"] is None  # PC initiative set by DM


@pytest.mark.asyncio
async def test_add_monster_midcombat_rolls_initiative(conn, campaign_id, session_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 1, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    result = await _add_combatant_impl(
        conn, enc["encounter_id"], "monster", "Goblin Boss", "reinforcements",
        campaign_id, session_id, ac=17, hp=21, dex_mod=1,
    )
    assert "error" not in result
    assert result["initiative"] is not None


# ─── P3.3 update_combatant ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_monster_damage_kills_at_zero(conn, campaign_id, session_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 1, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    goblin_id = enc["combatants"][0]["id"]
    result = await _update_combatant_impl(
        conn, goblin_id, "sword strike", campaign_id, session_id, None,
        damage={"amount": 10, "type": "slashing"},
    )
    assert result["hp_after"] == 0
    assert result["status"] == "dead"


@pytest.mark.asyncio
async def test_monster_nonlethal_goes_down(conn, campaign_id, session_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 1, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    goblin_id = enc["combatants"][0]["id"]
    result = await _update_combatant_impl(
        conn, goblin_id, "knock out", campaign_id, session_id, None,
        damage={"amount": 10, "type": "bludgeoning"}, nonlethal=True,
    )
    assert result["hp_after"] == 0
    assert result["status"] == "down"


@pytest.mark.asyncio
async def test_pc_damage_round_trips_to_character(conn, campaign_id, session_id, character_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 1, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    pc = await _add_combatant_impl(
        conn, enc["encounter_id"], "pc", "Kira", "joins", campaign_id, session_id,
        ref_id=character_id, initiative=15,
    )
    await _update_combatant_impl(
        conn, pc["combatant_id"], "goblin hits", campaign_id, session_id, None,
        damage={"amount": 7, "type": "piercing"},
    )
    # Verify characters table updated
    char = await repo.fetchone(conn, "SELECT hp FROM characters WHERE id=%s", (character_id,))
    assert char["hp"] == 23  # 30 - 7


@pytest.mark.asyncio
async def test_goblin_flees(conn, campaign_id, session_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 1, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    goblin_id = enc["combatants"][0]["id"]
    result = await _update_combatant_impl(
        conn, goblin_id, "goblin runs", campaign_id, session_id, None, status="fled",
    )
    assert result["status"] == "fled"


@pytest.mark.asyncio
async def test_concentration_effect_cleared_on_end_concentration(conn, campaign_id, session_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 2, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    g1, g2 = [c["id"] for c in enc["combatants"]]
    # Add a concentration effect sourced from goblin 1
    await _update_combatant_impl(
        conn, g2, "cursed", campaign_id, session_id, None,
        add_effect={
            "name": "Hex",
            "ends": "end_of_turn",
            "rounds_left": 10,
            "concentration": True,
            "source_combatant_id": g1,
            "anchor_combatant_id": g2,
        },
    )
    # End goblin 1's concentration
    result = await _update_combatant_impl(
        conn, g1, "concentration ended", campaign_id, session_id, None,
        end_concentration=True,
    )
    assert len(result.get("concentration_effects_ended", [])) == 1
    # Verify effect deleted
    effects = await repo.fetchall(
        conn, "SELECT * FROM effects WHERE encounter_id=%s", (enc["encounter_id"],)
    )
    assert len(effects) == 0


# ─── P3.4 next_turn ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_next_turn_advances_in_initiative_order(
    conn, campaign_id, session_id, character_id, character_id2
):
    encounter_id, goblin_ids, pc1_id, pc2_id = await _start_3goblin_fight(
        conn, campaign_id, session_id, character_id, character_id2
    )
    # Give goblins known initiatives: 20, 8, 5
    await conn.execute("UPDATE combatants SET initiative=20 WHERE id=%s", (goblin_ids[0],))
    await conn.execute("UPDATE combatants SET initiative=8  WHERE id=%s", (goblin_ids[1],))
    await conn.execute("UPDATE combatants SET initiative=5  WHERE id=%s", (goblin_ids[2],))
    # PC1=15, PC2=12, already set in fixture

    t1 = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t1["current"]["name"] == "Goblin 1"  # initiative 20

    t2 = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t2["current"]["initiative"] == 15  # Kira

    t3 = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t3["current"]["initiative"] == 12  # Mira


@pytest.mark.asyncio
async def test_next_turn_skips_dead_combatant(conn, campaign_id, session_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 3, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    encounter_id = enc["encounter_id"]
    g1, g2, g3 = [c["id"] for c in enc["combatants"]]
    # Set known initiatives and kill g2
    await conn.execute("UPDATE combatants SET initiative=20 WHERE id=%s", (g1,))
    await conn.execute("UPDATE combatants SET initiative=15, status='dead' WHERE id=%s", (g2,))
    await conn.execute("UPDATE combatants SET initiative=10 WHERE id=%s", (g3,))

    t1 = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t1["current"]["name"] == "Goblin 1"
    t2 = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t2["current"]["name"] == "Goblin 3"  # g2 skipped


@pytest.mark.asyncio
async def test_next_turn_death_save_due_for_downed_pc(
    conn, campaign_id, session_id, character_id, character_id2
):
    encounter_id, goblin_ids, pc1_id, pc2_id = await _start_3goblin_fight(
        conn, campaign_id, session_id, character_id, character_id2
    )
    # Drop PC1 to 0 HP
    await conn.execute("UPDATE characters SET hp=0 WHERE id=%s", (character_id,))
    await conn.execute("UPDATE combatants SET hp=0, initiative=20 WHERE id=%s", (pc1_id,))
    # Other combatants low initiative so PC1 goes first
    for gid in goblin_ids:
        await conn.execute("UPDATE combatants SET initiative=5 WHERE id=%s", (gid,))
    await conn.execute("UPDATE combatants SET initiative=3 WHERE id=%s", (pc2_id,))

    t = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t["current"]["combatant_id"] == pc1_id
    assert t["death_save_due"] is True


@pytest.mark.asyncio
async def test_next_turn_rounds_advance_on_wrap(conn, campaign_id, session_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 2, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    encounter_id = enc["encounter_id"]
    g1, g2 = [c["id"] for c in enc["combatants"]]
    await conn.execute("UPDATE combatants SET initiative=20 WHERE id=%s", (g1,))
    await conn.execute("UPDATE combatants SET initiative=10 WHERE id=%s", (g2,))

    t1 = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t1["round"] == 1
    t2 = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t2["round"] == 1
    t3 = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t3["round"] == 2  # wrapped around


@pytest.mark.asyncio
async def test_effect_expires_on_correct_boundary(conn, campaign_id, session_id):
    """1-round end_of_turn effect on g2 anchored to g1 expires after g1's first turn."""
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 2, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    encounter_id = enc["encounter_id"]
    g1, g2 = [c["id"] for c in enc["combatants"]]
    await conn.execute("UPDATE combatants SET initiative=20 WHERE id=%s", (g1,))
    await conn.execute("UPDATE combatants SET initiative=10 WHERE id=%s", (g2,))

    # Add 1-round end_of_turn effect anchored to g1
    await _update_combatant_impl(
        conn, g2, "cursed", campaign_id, session_id, None,
        add_effect={
            "name": "Bane",
            "ends": "end_of_turn",
            "rounds_left": 1,
            "concentration": False,
            "anchor_combatant_id": g1,
        },
    )

    # G1's turn starts — effect still alive
    t1 = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t1["current"]["name"] == "Goblin 1"
    assert len(t1["expired_effects"]) == 0

    # G2's turn starts — g1's end-of-turn passed → effect expires
    t2 = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t2["current"]["name"] == "Goblin 2"
    assert len(t2["expired_effects"]) == 1
    assert t2["expired_effects"][0]["name"] == "Bane"


@pytest.mark.asyncio
async def test_initiative_tie_broken_by_dex_then_tiebreak(conn, campaign_id, session_id):
    """Tie at initiative 15: g1 dex_mod=3, g2 dex_mod=1. g1 goes first."""
    enc = await _start_encounter_impl(
        conn, "Test",
        [
            {"name": "Goblin A", "count": 1, "ac": 15, "hp": 7, "dex_mod": 3},
            {"name": "Goblin B", "count": 1, "ac": 15, "hp": 7, "dex_mod": 1},
        ],
        "test", campaign_id, session_id, None,
    )
    encounter_id = enc["encounter_id"]
    ga_id, gb_id = enc["combatants"][0]["id"], enc["combatants"][1]["id"]
    # Force same initiative
    await conn.execute("UPDATE combatants SET initiative=15 WHERE id IN (%s,%s)", (ga_id, gb_id))

    t = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t["current"]["name"] == "Goblin A"  # higher dex_mod wins


# ─── P3.5 end_encounter ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_end_encounter_clears_state(conn, campaign_id, session_id):
    enc = await _start_encounter_impl(
        conn, "Test", [{"name": "Goblin", "count": 1, "ac": 15, "hp": 7}],
        "test", campaign_id, session_id, None,
    )
    encounter_id = enc["encounter_id"]

    result = await _end_encounter_impl(
        conn, encounter_id, "all dead", "Party wins", campaign_id, session_id
    )
    assert result["status"] == "ended"

    # get_state should return no active encounter
    state = await _get_state_impl(conn, campaign_id, ["encounter"])
    assert state["encounter"] is None


@pytest.mark.asyncio
async def test_full_scripted_fight(conn, campaign_id, session_id, character_id, character_id2):
    """§7.3 end-to-end: 2 PCs vs 3 goblins, reinforcement, flee, PC drops, effect expires."""
    # Step 1: Start encounter
    encounter_id, goblin_ids, pc1_id, pc2_id = await _start_3goblin_fight(
        conn, campaign_id, session_id, character_id, character_id2
    )
    assert len(goblin_ids) == 3

    # Force deterministic initiative: g1=18, g2=14, g3=6, pc1=15, pc2=12
    await conn.execute("UPDATE combatants SET initiative=18 WHERE id=%s", (goblin_ids[0],))
    await conn.execute("UPDATE combatants SET initiative=14 WHERE id=%s", (goblin_ids[1],))
    await conn.execute("UPDATE combatants SET initiative=6  WHERE id=%s", (goblin_ids[2],))
    await conn.execute("UPDATE combatants SET initiative=15 WHERE id=%s", (pc1_id,))
    await conn.execute("UPDATE combatants SET initiative=12 WHERE id=%s", (pc2_id,))

    # Round 1: 5 turns
    t = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t["current"]["name"] == "Goblin 1"  # 18

    t = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t["current"]["name"] == "Kira"      # 15

    t = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t["current"]["name"] == "Goblin 2"  # 14

    t = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t["current"]["name"] == "Mira"      # 12

    t = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t["current"]["name"] == "Goblin 3"  # 6
    assert t["round"] == 1

    # Step 2: Round 2 starts — add reinforcement
    t = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t["round"] == 2
    reinforcement = await _add_combatant_impl(
        conn, encounter_id, "monster", "Goblin Boss", "reinforcements",
        campaign_id, session_id, ac=17, hp=21, dex_mod=1,
    )
    assert "error" not in reinforcement

    # Step 3: One goblin flees
    await _update_combatant_impl(
        conn, goblin_ids[2], "goblin flees", campaign_id, session_id, None, status="fled"
    )
    comb = await repo.fetchone(conn, "SELECT status FROM combatants WHERE id=%s", (goblin_ids[2],))
    assert comb["status"] == "fled"

    # Step 4: Drop PC1 to 0 HP
    await conn.execute("UPDATE characters SET hp=0 WHERE id=%s", (character_id,))
    await conn.execute("UPDATE combatants SET hp=0, status='down' WHERE id=%s", (pc1_id,))

    # Step 5: PC1's turn — death_save_due
    # Wind to PC1's turn by setting its initiative very high
    await conn.execute("UPDATE combatants SET initiative=100 WHERE id=%s", (pc1_id,))
    # Reset encounter turn_index to trigger next_turn
    await conn.execute("UPDATE encounters SET turn_index=-1, round=3 WHERE id=%s", (encounter_id,))
    t = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)
    assert t["current"]["combatant_id"] == pc1_id
    assert t["death_save_due"] is True

    # Step 6: 1-round effect test
    # Add 1-round start_of_turn effect anchored to Goblin 2
    await _update_combatant_impl(
        conn, goblin_ids[0], "marked", campaign_id, session_id, None,
        add_effect={
            "name": "Hunter's Mark",
            "ends": "start_of_turn",
            "rounds_left": 1,
            "concentration": False,
            "anchor_combatant_id": goblin_ids[1],
        },
    )
    # Set goblin 2 to go before goblin 1 now
    await conn.execute("UPDATE combatants SET initiative=50 WHERE id=%s", (goblin_ids[1],))
    await conn.execute("UPDATE combatants SET initiative=1  WHERE id=%s", (goblin_ids[0],))
    await conn.execute("UPDATE encounters SET turn_index=-1 WHERE id=%s", (encounter_id,))

    t = await _next_turn_impl(conn, encounter_id, campaign_id, session_id)  # goblin 2 start
    assert t["current"]["combatant_id"] == goblin_ids[1]
    # Start-of-turn effects for goblin 2 fire → Hunter's Mark expires
    assert any(e["name"] == "Hunter's Mark" for e in t["expired_effects"])

    # End encounter
    result = await _end_encounter_impl(
        conn, encounter_id, "fight over", "Goblins defeated", campaign_id, session_id
    )
    assert result["status"] == "ended"
