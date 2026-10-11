"""Integration tests for Phase 4 world tools. Skipped without SUPABASE_URL.

Acceptance criteria:
- get_npc default omits knows; dm_view=true includes knows
- get_npc never includes secrets
- get_secrets requires scoped query; no list-all
- tick_clock returns consequence only on fill
- hidden clock: get_state omits consequence
- lore FTS finds by partial match; dm_only flagged
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from tests.conftest import DB_URL

skip = pytest.mark.skipif(not DB_URL, reason="SUPABASE_URL not set")
pytestmark = skip

from tools.world import (
    _upsert_npc_impl,
    _get_npc_impl,
    _upsert_location_impl,
    _get_location_impl,
    _add_secret_impl,
    _get_secrets_impl,
    _reveal_secret_impl,
    _upsert_quest_impl,
    _upsert_clock_impl,
    _tick_clock_impl,
    _upsert_lore_impl,
    _get_lore_impl,
)
from tools.state import _get_state_impl
from db import repo


# ─── P4.1 NPCs ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_npc_creates(conn, campaign_id):
    result = await _upsert_npc_impl(
        conn, "Zara the Innkeeper", "intro", campaign_id, None, None,
        role="innkeeper", disposition=2, wants="peace", fears="dragons",
        knows="The mayor is corrupt.",
    )
    assert "error" not in result
    assert "npc_id" in result


@pytest.mark.asyncio
async def test_get_npc_omits_knows_by_default(conn, campaign_id):
    r = await _upsert_npc_impl(
        conn, "Zara", "test", campaign_id, None, None, knows="She spies for the guild."
    )
    npc = await _get_npc_impl(conn, "Zara", campaign_id, dm_view=False)
    assert "error" not in npc
    assert "knows" not in npc


@pytest.mark.asyncio
async def test_get_npc_dm_view_includes_knows(conn, campaign_id):
    await _upsert_npc_impl(
        conn, "Zara", "test", campaign_id, None, None, knows="She spies for the guild."
    )
    npc = await _get_npc_impl(conn, "Zara", campaign_id, dm_view=True)
    assert npc["knows"] == "She spies for the guild."


@pytest.mark.asyncio
async def test_get_npc_never_returns_secrets(conn, campaign_id):
    r = await _upsert_npc_impl(conn, "Zara", "test", campaign_id, None, None)
    await _add_secret_impl(
        conn, "Zara is a vampire", "npc", "secret", campaign_id, None, None,
        tied_to_id=r["npc_id"],
    )
    npc = await _get_npc_impl(conn, "Zara", campaign_id, dm_view=True)
    assert "secrets" not in npc
    assert "vampire" not in str(npc)


@pytest.mark.asyncio
async def test_get_npc_by_uuid(conn, campaign_id):
    r = await _upsert_npc_impl(conn, "Zara", "test", campaign_id, None, None)
    npc = await _get_npc_impl(conn, r["npc_id"], campaign_id, dm_view=False)
    assert npc["name"] == "Zara"


@pytest.mark.asyncio
async def test_get_npc_ambiguous_name(conn, campaign_id):
    await _upsert_npc_impl(conn, "Bob", "test", campaign_id, None, None)
    await _upsert_npc_impl(conn, "Bob", "test2", campaign_id, None, None)
    result = await _get_npc_impl(conn, "Bob", campaign_id, dm_view=False)
    assert "error" in result
    assert "ambiguous" in result["error"]


@pytest.mark.asyncio
async def test_upsert_npc_updates_by_id(conn, campaign_id):
    r = await _upsert_npc_impl(conn, "Zara", "create", campaign_id, None, None, disposition=0)
    # Update using id
    r2 = await _upsert_npc_impl(
        conn, "Zara", "update", campaign_id, None, None,
        id=r["npc_id"], disposition=3, wants="gold",
    )
    npc = await _get_npc_impl(conn, r["npc_id"], campaign_id, dm_view=False)
    assert npc["disposition"] == 3
    assert npc["wants"] == "gold"


# ─── P4.2 Locations ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_location_creates(conn, campaign_id):
    result = await _upsert_location_impl(
        conn, "Stormwreck Isle", "intro", campaign_id, None, None,
        region="Sea of Swords", description="A storm-wracked island.",
    )
    assert "location_id" in result


@pytest.mark.asyncio
async def test_get_location_by_name(conn, campaign_id):
    await _upsert_location_impl(conn, "Dragon's Lair", "test", campaign_id, None, None)
    loc = await _get_location_impl(conn, "Dragon's Lair", campaign_id)
    assert loc["name"] == "Dragon's Lair"


@pytest.mark.asyncio
async def test_get_location_not_found(conn, campaign_id):
    result = await _get_location_impl(conn, "Nonexistent Place", campaign_id)
    assert "error" in result


# ─── P4.3 Secrets ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_add_secret_requires_valid_type(conn, campaign_id):
    result = await _add_secret_impl(
        conn, "text", "invalid_type", "test", campaign_id, None, None
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_get_secrets_scoped_by_type_and_id(conn, campaign_id):
    npc_r = await _upsert_npc_impl(conn, "Zara", "test", campaign_id, None, None)
    npc_id = npc_r["npc_id"]
    await _add_secret_impl(
        conn, "Zara is a spy", "npc", "test", campaign_id, None, None,
        tied_to_id=npc_id,
    )
    await _add_secret_impl(
        conn, "The village hides treasure", "none", "test", campaign_id, None, None,
    )
    # Scoped to npc: returns only Zara's secret
    result = await _get_secrets_impl(conn, "npc", campaign_id, npc_id)
    assert len(result["secrets"]) == 1
    assert "spy" in result["secrets"][0]["text"]


@pytest.mark.asyncio
async def test_get_secrets_none_type_requires_null_id(conn, campaign_id):
    await _add_secret_impl(
        conn, "Global secret", "none", "test", campaign_id, None, None,
    )
    result = await _get_secrets_impl(conn, "none", campaign_id, None)
    assert len(result["secrets"]) >= 1
    assert any("Global secret" in s["text"] for s in result["secrets"])


@pytest.mark.asyncio
async def test_reveal_secret(conn, campaign_id):
    r = await _add_secret_impl(
        conn, "The mayor is a lich", "none", "test", campaign_id, None, None,
    )
    rev = await _reveal_secret_impl(
        conn, r["secret_id"], "Players found the phylactery", campaign_id, None, None
    )
    assert rev["revealed"]
    # Verify in DB
    row = await repo.fetchone(conn, "SELECT revealed, revealed_how FROM secrets WHERE id=%s", (r["secret_id"],))
    assert row["revealed"]
    assert "phylactery" in row["revealed_how"]


@pytest.mark.asyncio
async def test_no_list_all_secrets_tool(conn, campaign_id):
    """Confirm get_secrets requires tied_to_type — no way to dump all secrets."""
    # get_secrets without both scope args returns scoped results, never all
    result = await _get_secrets_impl(conn, "invalid_type", campaign_id, None)
    assert "error" in result


# ─── P4.4 Quests + Clocks ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_quest_lifecycle(conn, campaign_id):
    r = await _upsert_quest_impl(
        conn, "Find the stolen idol", "intro", campaign_id, None, None,
        status="rumor", summary="Villagers say it's in the forest.",
    )
    assert "quest_id" in r
    # Promote to active
    r2 = await _upsert_quest_impl(
        conn, "Find the stolen idol", "activated", campaign_id, None, None,
        id=r["quest_id"], status="active",
    )
    assert r2["status"] == "active"


@pytest.mark.asyncio
async def test_upsert_quest_invalid_status(conn, campaign_id):
    result = await _upsert_quest_impl(
        conn, "Test", "test", campaign_id, None, None, status="ongoing"
    )
    assert "error" in result


@pytest.mark.asyncio
async def test_tick_clock_partial_no_consequence(conn, campaign_id):
    r = await _upsert_clock_impl(
        conn, "Dragon Awakens", 6, "create", campaign_id, None, None,
        consequence="Dragon destroys the village",
    )
    tick = await _tick_clock_impl(
        conn, r["clock_id"], 2, "ticked", campaign_id, None, None,
    )
    assert tick["filled"] == 2
    assert tick["filled_now"] is False
    assert "consequence" not in tick


@pytest.mark.asyncio
async def test_tick_clock_to_fill_returns_consequence(conn, campaign_id):
    r = await _upsert_clock_impl(
        conn, "Dragon Awakens", 4, "create", campaign_id, None, None,
        consequence="Dragon destroys the village", filled=3,
    )
    tick = await _tick_clock_impl(
        conn, r["clock_id"], 1, "final tick", campaign_id, None, None,
    )
    assert tick["filled_now"] is True
    assert tick["consequence"] == "Dragon destroys the village"


@pytest.mark.asyncio
async def test_tick_clock_clamps_at_segments(conn, campaign_id):
    r = await _upsert_clock_impl(
        conn, "Short Clock", 3, "create", campaign_id, None, None,
        filled=2,
    )
    tick = await _tick_clock_impl(
        conn, r["clock_id"], 5, "overshoot", campaign_id, None, None,
    )
    assert tick["filled"] == 3  # clamped


@pytest.mark.asyncio
async def test_hidden_clock_get_state_no_consequence(conn, campaign_id):
    r = await _upsert_clock_impl(
        conn, "Hidden Doom", 6, "create", campaign_id, None, None,
        consequence="Apocalypse", visible=False, filled=2,
    )
    state = await _get_state_impl(conn, campaign_id, ["clocks"])
    clock = next((c for c in state["clocks"] if c["name"] == "Hidden Doom"), None)
    assert clock is not None
    assert clock["filled"] == 2
    assert "consequence" not in clock


# ─── P4.5 Lore ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_lore_and_exact_search(conn, campaign_id):
    await _upsert_lore_impl(
        conn, "The Dragon Cult", "Worshippers of Scales", [], False,
        "world lore", campaign_id, None, None,
    )
    result = await _get_lore_impl(conn, "The Dragon Cult", campaign_id)
    assert len(result["results"]) >= 1
    assert result["results"][0]["title"] == "The Dragon Cult"


@pytest.mark.asyncio
async def test_lore_fts_partial_match(conn, campaign_id):
    await _upsert_lore_impl(
        conn, "Stormwreck History",
        "The island was cursed by a dying dragon who sought revenge.",
        [], False, "world lore", campaign_id, None, None,
    )
    result = await _get_lore_impl(conn, "cursed island dragon", campaign_id)
    assert len(result["results"]) >= 1


@pytest.mark.asyncio
async def test_lore_dm_only_flagged(conn, campaign_id):
    await _upsert_lore_impl(
        conn, "True Name of the Villain", "His name is Malachar, not revealed.",
        [], True, "dm secret", campaign_id, None, None,
    )
    result = await _get_lore_impl(conn, "True Name of the Villain", campaign_id)
    assert len(result["results"]) >= 1
    assert result["results"][0]["dm_only"] is True


@pytest.mark.asyncio
async def test_lore_upsert_updates_by_id(conn, campaign_id):
    r = await _upsert_lore_impl(
        conn, "Old Lore", "Original body.", [], False, "create", campaign_id, None, None,
    )
    await _upsert_lore_impl(
        conn, "Old Lore", "Updated body.", [], False, "update",
        campaign_id, None, None, id=r["lore_id"],
    )
    result = await _get_lore_impl(conn, "Old Lore", campaign_id)
    assert "Updated body" in result["results"][0]["body"]
