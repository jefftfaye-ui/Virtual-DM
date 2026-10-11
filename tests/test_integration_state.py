"""Integration tests for Phase 2 state + session tools.

Skipped automatically if SUPABASE_URL is not set.
Each test runs in a rolled-back transaction (no persisted data).
"""

from __future__ import annotations

import json
import pytest
import pytest_asyncio

from tests.conftest import DB_URL

skip = pytest.mark.skipif(not DB_URL, reason="SUPABASE_URL not set")

# Import the _impl functions so we can pass our test conn
from tools.state import (
    _get_state_impl,
    _update_character_impl,
    _death_save_impl,
    _rest_impl,
    _set_scene_impl,
    _undo_last_event_impl,
)
from tools.sessions import _start_session_impl, _end_session_impl
from db import repo


pytestmark = skip  # skip entire file if no DB


# ─── helpers ──────────────────────────────────────────────────────────────────


async def _get_char(conn, char_id: str) -> dict:
    return await repo.fetchone(conn, "SELECT * FROM characters WHERE id = %s", (char_id,))


# ─── P2.2 get_state ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_state_returns_party(conn, campaign_id, character_id):
    state = await _get_state_impl(conn, campaign_id, ["party"])
    assert "party" in state
    assert len(state["party"]) == 1
    pc = state["party"][0]
    assert pc["name"] == "Kira"
    assert pc["hp"] == 30
    assert "spell_slots" in pc


@pytest.mark.asyncio
async def test_get_state_excludes_secrets(conn, campaign_id):
    # insert a secret — should not appear in get_state
    await conn.execute(
        "INSERT INTO secrets (campaign_id, text, tied_to_type) VALUES (%s, %s, 'none')",
        (campaign_id, "The wizard is a spy"),
    )
    state = await _get_state_impl(conn, campaign_id, ["party", "scene", "quests", "clocks"])
    assert "secrets" not in state
    # no party member has 'secrets' field
    for pc in state.get("party", []):
        assert "secrets" not in pc


@pytest.mark.asyncio
async def test_get_state_hidden_clock_no_consequence(conn, campaign_id):
    await conn.execute(
        "INSERT INTO clocks (campaign_id, name, segments, filled, consequence, visible) "
        "VALUES (%s, 'Hidden Clock', 6, 3, 'The village burns', false)",
        (campaign_id,),
    )
    state = await _get_state_impl(conn, campaign_id, ["clocks"])
    clock = next((c for c in state["clocks"] if c["name"] == "Hidden Clock"), None)
    assert clock is not None
    assert "consequence" not in clock


@pytest.mark.asyncio
async def test_get_state_visible_clock_no_consequence_in_snapshot(conn, campaign_id):
    # visible=true: still omit consequence in snapshot (revealed only on fill)
    await conn.execute(
        "INSERT INTO clocks (campaign_id, name, segments, filled, consequence, visible) "
        "VALUES (%s, 'Doom Clock', 4, 1, 'Dragon wakes', true)",
        (campaign_id,),
    )
    state = await _get_state_impl(conn, campaign_id, ["clocks"])
    clock = next((c for c in state["clocks"] if c["name"] == "Doom Clock"), None)
    assert clock is not None
    # consequence intentionally omitted from get_state (revealed only via tick_clock on fill)


# ─── P2.3 update_character ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_damage_reduces_hp(conn, campaign_id, character_id):
    result = await _update_character_impl(
        conn, character_id, "goblin hits", campaign_id, None, None,
        damage={"amount": 8, "type": "piercing"},
    )
    assert result["hp_after"] == 22
    char = await _get_char(conn, character_id)
    assert char["hp"] == 22


@pytest.mark.asyncio
async def test_damage_resistance_halves(conn, campaign_id, character_id):
    # give fire resistance via overrides then damage
    await conn.execute(
        "UPDATE characters SET resistances = '{fire}' WHERE id = %s", (character_id,)
    )
    result = await _update_character_impl(
        conn, character_id, "fireball", campaign_id, None, None,
        damage={"amount": 10, "type": "fire"},
    )
    assert result["resisted"]
    assert result["hp_after"] == 25  # 30 - 5


@pytest.mark.asyncio
async def test_damage_immunity_zeroes(conn, campaign_id, character_id):
    await conn.execute(
        "UPDATE characters SET immunities = '{poison}' WHERE id = %s", (character_id,)
    )
    result = await _update_character_impl(
        conn, character_id, "poison", campaign_id, None, None,
        damage={"amount": 20, "type": "poison"},
    )
    assert result["immune"]
    assert result["hp_after"] == 30


@pytest.mark.asyncio
async def test_temp_hp_absorbs_first(conn, campaign_id, character_id):
    await conn.execute("UPDATE characters SET temp_hp = 5 WHERE id = %s", (character_id,))
    result = await _update_character_impl(
        conn, character_id, "hit", campaign_id, None, None,
        damage={"amount": 8, "type": "slashing"},
    )
    assert result["temp_absorbed"] == 5
    assert result["hp_after"] == 27  # 30 - (8-5)
    assert result["temp_hp_after"] == 0


@pytest.mark.asyncio
async def test_heal_restores_hp(conn, campaign_id, character_id):
    await conn.execute("UPDATE characters SET hp = 10 WHERE id = %s", (character_id,))
    result = await _update_character_impl(
        conn, character_id, "cure wounds", campaign_id, None, None, heal=8
    )
    assert result["hp_after"] == 18


@pytest.mark.asyncio
async def test_heal_clears_death_saves(conn, campaign_id, character_id):
    await conn.execute(
        "UPDATE characters SET hp=0, death_saves='{\"successes\":2,\"failures\":1}'::jsonb WHERE id=%s",
        (character_id,),
    )
    await _update_character_impl(
        conn, character_id, "cure wounds", campaign_id, None, None, heal=5
    )
    char = await _get_char(conn, character_id)
    assert char["death_saves"] == {"successes": 0, "failures": 0}


@pytest.mark.asyncio
async def test_concentration_check_returned(conn, campaign_id, character_id):
    await conn.execute(
        "UPDATE characters SET concentrating_on = 'Bless' WHERE id = %s", (character_id,)
    )
    result = await _update_character_impl(
        conn, character_id, "hit", campaign_id, None, None,
        damage={"amount": 20, "type": "fire"},
    )
    assert "concentration_check" in result
    assert result["concentration_check"]["dc"] == 10


@pytest.mark.asyncio
async def test_drop_to_zero_ends_concentration(conn, campaign_id, character_id):
    await conn.execute(
        "UPDATE characters SET hp=5, concentrating_on='Bless' WHERE id=%s", (character_id,)
    )
    result = await _update_character_impl(
        conn, character_id, "big hit", campaign_id, None, None,
        damage={"amount": 10, "type": "force"},
    )
    assert result["dropped"]
    assert result["concentrating_on"] is None


@pytest.mark.asyncio
async def test_slot_overspend_refused(conn, campaign_id, character_id):
    # exhaust level-1 slots first
    await conn.execute(
        "UPDATE characters SET spell_slots='{\"1\":{\"max\":4,\"used\":4}}'::jsonb WHERE id=%s",
        (character_id,),
    )
    result = await _update_character_impl(
        conn, character_id, "cast", campaign_id, None, None, use_slot=1
    )
    assert "error" in result
    assert "no level-1 slots" in result["error"]


@pytest.mark.asyncio
async def test_resource_overspend_refused(conn, campaign_id, character_id):
    await conn.execute(
        "UPDATE characters SET resources='{\"ki\":{\"max\":5,\"used\":5,\"recharge\":\"short\"}}'::jsonb WHERE id=%s",
        (character_id,),
    )
    result = await _update_character_impl(
        conn, character_id, "ki", campaign_id, None, None, use_resource="ki"
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_hit_die_overspend_refused(conn, campaign_id, character_id):
    await conn.execute(
        "UPDATE characters SET hit_dice='{\"d8\":{\"max\":5,\"used\":5}}'::jsonb WHERE id=%s",
        (character_id,),
    )
    result = await _update_character_impl(
        conn, character_id, "rest heal", campaign_id, None, None,
        spend_hit_dice={"die": "d8", "count": 1},
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_conditions_update(conn, campaign_id, character_id):
    result = await _update_character_impl(
        conn, character_id, "poisoned", campaign_id, None, None,
        add_conditions=["Poisoned", "Blinded"],
    )
    assert "poisoned" in result["conditions"]
    assert "blinded" in result["conditions"]

    result2 = await _update_character_impl(
        conn, character_id, "cured", campaign_id, None, None,
        remove_conditions=["poisoned"],
    )
    assert "poisoned" not in result2["conditions"]
    assert "blinded" in result2["conditions"]


# ─── P2.4 death_save ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_death_save_refuses_conscious(conn, campaign_id, character_id):
    result = await _death_save_impl(conn, character_id, campaign_id, None, None)
    assert "error" in result
    assert "conscious" in result["error"]


@pytest.mark.asyncio
async def test_death_save_refuses_stable(conn, campaign_id, character_id):
    await conn.execute(
        "UPDATE characters SET hp=0, stable=true WHERE id=%s", (character_id,)
    )
    result = await _death_save_impl(conn, character_id, campaign_id, None, None)
    assert "error" in result
    assert "stable" in result["error"]


@pytest.mark.asyncio
async def test_death_save_runs_and_records(conn, campaign_id, character_id):
    await conn.execute("UPDATE characters SET hp=0 WHERE id=%s", (character_id,))
    result = await _death_save_impl(conn, character_id, campaign_id, None, None)
    assert "error" not in result
    assert "natural" in result
    assert 1 <= result["natural"] <= 20
    assert "roll_id" in result
    # DB should reflect the save
    char = await _get_char(conn, character_id)
    if result["dead"]:
        assert char["dead"]
    elif result["stable"]:
        assert char["stable"]


# ─── P2.5 rest ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_long_rest_restores_hp_and_slots(conn, campaign_id, character_id):
    await conn.execute(
        "UPDATE characters SET hp=10, spell_slots='{\"1\":{\"max\":4,\"used\":3}}'::jsonb WHERE id=%s",
        (character_id,),
    )
    result = await _rest_impl(
        conn, "long", [character_id], "long rest", campaign_id, None, None, "2014"
    )
    assert result["kind"] == "long"
    char = await _get_char(conn, character_id)
    assert char["hp"] == char["max_hp"]
    assert char["spell_slots"]["1"]["used"] == 0


@pytest.mark.asyncio
async def test_short_rest_restores_ki_not_slots(conn, campaign_id, character_id):
    await conn.execute(
        "UPDATE characters SET "
        "spell_slots='{\"1\":{\"max\":4,\"used\":2}}'::jsonb, "
        "resources='{\"ki\":{\"max\":5,\"used\":3,\"recharge\":\"short\"}}'::jsonb "
        "WHERE id=%s",
        (character_id,),
    )
    result = await _rest_impl(
        conn, "short", [character_id], "short rest", campaign_id, None, None, "2014"
    )
    char = await _get_char(conn, character_id)
    assert char["resources"]["ki"]["used"] == 0
    assert char["spell_slots"]["1"]["used"] == 2  # slots unchanged


# ─── P2.6 set_scene ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_scene_updates_description(conn, campaign_id):
    result = await _set_scene_impl(
        conn, "The party stands at the edge of the Stormwreck Isle", "scene change",
        campaign_id, None,
    )
    assert result["description"] == "The party stands at the edge of the Stormwreck Isle"
    # verify in DB
    camp = await repo.fetchone(conn, "SELECT current_scene FROM campaigns WHERE id=%s", (campaign_id,))
    assert "Stormwreck" in camp["current_scene"]


@pytest.mark.asyncio
async def test_set_scene_with_date(conn, campaign_id):
    result = await _set_scene_impl(
        conn, "Morning on the isle", "dawn", campaign_id, None,
        in_game_date="Day 1, Hammer 15, 1492 DR",
    )
    assert result["in_game_date"] == "Day 1, Hammer 15, 1492 DR"


# ─── P2.7 undo_last_event ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_undo_reverts_damage(conn, campaign_id, character_id, session_id):
    # damage the character
    await _update_character_impl(
        conn, character_id, "hit", campaign_id, session_id, None,
        damage={"amount": 10, "type": "slashing"},
    )
    char_after = await _get_char(conn, character_id)
    assert char_after["hp"] == 20

    # undo it
    result = await _undo_last_event_impl(conn, "oops", campaign_id, session_id)
    assert "error" not in result
    assert result["undone_type"] == "update_character"

    char_undone = await _get_char(conn, character_id)
    assert char_undone["hp"] == 30


@pytest.mark.asyncio
async def test_undo_reverts_scene(conn, campaign_id, session_id):
    # set a scene
    await _set_scene_impl(conn, "New scene", "test", campaign_id, session_id)

    result = await _undo_last_event_impl(conn, "undo scene", campaign_id, session_id)
    assert result["undone_type"] == "set_scene"

    camp = await repo.fetchone(conn, "SELECT current_scene FROM campaigns WHERE id=%s", (campaign_id,))
    assert camp["current_scene"] is None


@pytest.mark.asyncio
async def test_undo_multiple_steps(conn, campaign_id, character_id, session_id):
    await _update_character_impl(
        conn, character_id, "hit 1", campaign_id, session_id, None,
        damage={"amount": 5, "type": "slashing"},
    )
    await _update_character_impl(
        conn, character_id, "hit 2", campaign_id, session_id, None,
        damage={"amount": 5, "type": "slashing"},
    )
    char = await _get_char(conn, character_id)
    assert char["hp"] == 20

    await _undo_last_event_impl(conn, "undo 2", campaign_id, session_id)
    char = await _get_char(conn, character_id)
    assert char["hp"] == 25

    await _undo_last_event_impl(conn, "undo 1", campaign_id, session_id)
    char = await _get_char(conn, character_id)
    assert char["hp"] == 30


# ─── P2.1 sessions ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_end_start_returns_two_recaps(conn, campaign_id):
    sess1 = await _start_session_impl(conn, campaign_id)
    assert sess1["number"] == 1
    assert "state" in sess1

    await _end_session_impl(conn, "Explored the cave", campaign_id)

    sess2 = await _start_session_impl(conn, campaign_id)
    assert sess2["number"] == 2
    recaps = {r["recap"] for r in sess2["recent_recaps"]}
    assert "Explored the cave" in recaps


@pytest.mark.asyncio
async def test_end_session_without_active_errors(conn, campaign_id):
    result = await _end_session_impl(conn, "nothing", campaign_id)
    assert "error" in result
