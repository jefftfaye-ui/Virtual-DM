"""Integration tests for Phase 5 rule/monster lookups. Skipped without SUPABASE_URL.

Seeds a small set of SRD chunks directly into the test transaction.
Covers SPEC §7.5 acceptance:
- lookup_rule("grappled") → exact stage 1
- lookup_rule("grapple") → trigram stage 2
- lookup_monster("goblin") → full stat block + meta
- fuzzy misspelling still matches
- SRD content roundtrip via start_encounter statblock_ref
"""

from __future__ import annotations

import json
import pytest
import pytest_asyncio

from tests.conftest import DB_URL

skip = pytest.mark.skipif(not DB_URL, reason="SUPABASE_URL not set")
pytestmark = skip

from tools.rules import _lookup_impl, _lookup_monster_meta
from tools.combat import _start_encounter_impl
from rules.statblock import normalize_name, extract_monster_meta, format_monster_body
from db import repo


# ─── fixtures: seed SRD data into the test transaction ────────────────────────

_GOBLIN = {
    "name": "Goblin",
    "size": "Small", "type": "humanoid", "alignment": "neutral evil",
    "hit_points": 7, "hit_dice": "2d6",
    "armor_class": [{"value": 15, "type": "leather armor, shield"}],
    "speed": {"walk": "30 ft."},
    "strength": 8, "dexterity": 14, "constitution": 10,
    "intelligence": 10, "wisdom": 8, "charisma": 8,
    "damage_resistances": [], "damage_immunities": [],
    "damage_vulnerabilities": [], "condition_immunities": [],
    "challenge_rating": "1/4", "xp": 50,
    "special_abilities": [], "actions": [
        {"name": "Scimitar", "desc": "+4 to hit, 1d6+2 slashing damage."},
        {"name": "Shortbow", "desc": "+4 to hit, 1d6+2 piercing damage."},
    ], "legendary_actions": [],
}

_GRAPPLED_CONDITION = {
    "name": "Grappled",
    "desc": [
        "A grappled creature's speed becomes 0, and it can't benefit from any bonus to its speed.",
        "The condition ends if the grappler is incapacitated.",
        "The condition also ends if an effect removes the grappled creature from the reach of the grappler or grappling effect.",
    ],
}

_GRAPPLE_RULE = {
    "name": "Grappling",
    "desc": "When you want to grab a creature or wrestle with it, you can use the Attack action to make a special melee attack, a grapple.",
    "subsections": [],
}


@pytest_asyncio.fixture
async def seeded_srd(conn):
    """Insert test SRD chunks. Returns dict of name→id."""
    ids = {}
    # Goblin monster
    meta = extract_monster_meta(_GOBLIN)
    body = format_monster_body(_GOBLIN)
    row = await repo.fetchone(
        conn,
        "INSERT INTO srd_chunks (edition, kind, name, name_norm, body, meta) "
        "VALUES ('2014','monster',%s,%s,%s,%s::jsonb) RETURNING id",
        ("Goblin", normalize_name("Goblin"), body, json.dumps(meta)),
    )
    ids["goblin"] = str(row["id"])

    # Grappled condition
    cond_body = "Grappled\n" + "\n".join(_GRAPPLED_CONDITION["desc"])
    row = await repo.fetchone(
        conn,
        "INSERT INTO srd_chunks (edition, kind, name, name_norm, body) "
        "VALUES ('2014','condition',%s,%s,%s) RETURNING id",
        ("Grappled", normalize_name("Grappled"), cond_body),
    )
    ids["grappled"] = str(row["id"])

    # Grappling rule
    rule_body = "Grappling\n" + _GRAPPLE_RULE["desc"]
    row = await repo.fetchone(
        conn,
        "INSERT INTO srd_chunks (edition, kind, name, name_norm, body) "
        "VALUES ('2014','rule',%s,%s,%s) RETURNING id",
        ("Grappling", normalize_name("Grappling"), rule_body),
    )
    ids["grapple_rule"] = str(row["id"])
    return ids


# ─── lookup_rule ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lookup_rule_exact_grappled(conn, seeded_srd):
    result = await _lookup_impl(conn, "grappled", "2014", None, False)
    assert result["stage"] == "exact"
    assert any(r["name"] == "Grappled" for r in result["results"])


@pytest.mark.asyncio
async def test_lookup_rule_trigram_grapple(conn, seeded_srd):
    # "grapple" ≠ "grappled" exact, but similarity > 0.3
    result = await _lookup_impl(conn, "grapple", "2014", None, False)
    assert result["stage"] in ("exact", "trigram")
    assert len(result["results"]) >= 1


@pytest.mark.asyncio
async def test_lookup_rule_fts_by_body(conn, seeded_srd):
    result = await _lookup_impl(conn, "speed becomes 0", "2014", None, False)
    assert len(result["results"]) >= 1
    names = [r["name"] for r in result["results"]]
    assert "Grappled" in names


@pytest.mark.asyncio
async def test_lookup_rule_not_found(conn, seeded_srd):
    result = await _lookup_impl(conn, "xyzzy nonexistent rule", "2014", None, False)
    assert result["results"] == []


@pytest.mark.asyncio
async def test_lookup_rule_body_trimmed(conn, seeded_srd):
    result = await _lookup_impl(conn, "grappled", "2014", None, False)
    for r in result["results"]:
        assert len(r["body"]) <= 1600  # 1500 + a bit for the ellipsis line


# ─── lookup_monster ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lookup_monster_exact(conn, seeded_srd):
    result = await _lookup_impl(conn, "goblin", "2014", "monster", True)
    assert result["stage"] == "exact"
    assert result["results"][0]["name"] == "Goblin"
    assert "meta" in result["results"][0]
    assert result["results"][0]["meta"]["hp"] == 7
    assert result["results"][0]["meta"]["ac"] == 15


@pytest.mark.asyncio
async def test_lookup_monster_full_body_not_truncated(conn, seeded_srd):
    result = await _lookup_impl(conn, "goblin", "2014", "monster", True)
    body = result["results"][0]["body"]
    assert "Goblin" in body
    assert "Scimitar" in body


@pytest.mark.asyncio
async def test_lookup_monster_fuzzy(conn, seeded_srd):
    # "goblins" or "gobline" should still find Goblin via trigram
    result = await _lookup_impl(conn, "goblins", "2014", "monster", True)
    assert len(result["results"]) >= 1
    assert result["results"][0]["name"] == "Goblin"


# ─── _lookup_monster_meta ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lookup_monster_meta_returns_structured(conn, seeded_srd):
    meta = await _lookup_monster_meta(conn, "Goblin", "2014")
    assert meta is not None
    assert meta["ac"] == 15
    assert meta["hp"] == 7
    assert meta["dex_mod"] == 2


@pytest.mark.asyncio
async def test_lookup_monster_meta_fuzzy(conn, seeded_srd):
    meta = await _lookup_monster_meta(conn, "gobline", "2014")
    assert meta is not None
    assert meta["hp"] == 7


@pytest.mark.asyncio
async def test_lookup_monster_meta_not_found(conn, seeded_srd):
    meta = await _lookup_monster_meta(conn, "Beholder", "2014")
    assert meta is None


# ─── start_encounter with statblock_ref ───────────────────────────────────────

@pytest.mark.asyncio
async def test_start_encounter_uses_statblock_ref(conn, campaign_id, session_id, seeded_srd):
    """start_encounter with statblock_ref='Goblin' pulls AC+HP+dex_mod from SRD."""
    enc = await _start_encounter_impl(
        conn,
        "Goblin Raid",
        [{"name": "Goblin", "count": 2, "statblock_ref": "Goblin"}],
        "test",
        campaign_id, session_id, None,
    )
    assert "error" not in enc, enc
    for c in enc["combatants"]:
        assert c["hp"] == 7
        # Name should be auto-numbered
    names = [c["name"] for c in enc["combatants"]]
    assert "Goblin 1" in names and "Goblin 2" in names


@pytest.mark.asyncio
async def test_start_encounter_explicit_overrides_statblock(conn, campaign_id, session_id, seeded_srd):
    """Explicit ac/hp override SRD values."""
    enc = await _start_encounter_impl(
        conn,
        "Boss Fight",
        [{"name": "Goblin", "count": 1, "statblock_ref": "Goblin", "ac": 20, "hp": 50}],
        "test",
        campaign_id, session_id, None,
    )
    assert "error" not in enc
    assert enc["combatants"][0]["hp"] == 50
