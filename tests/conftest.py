"""Pytest fixtures for integration tests.

Tools expose `_impl(conn, ...)` functions. Tests pass their own connection
and roll back after each test — no data persists between tests.

Requires SUPABASE_URL env var pointing at a dev Postgres with schema applied:
    psql "$SUPABASE_URL" -f db/schema.sql
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
import pytest_asyncio

DB_URL = os.environ.get("SUPABASE_URL", "")


@pytest_asyncio.fixture
async def conn():
    """Async connection that rolls back after each test."""
    if not DB_URL:
        pytest.skip("SUPABASE_URL not set")

    from psycopg import AsyncConnection

    c = await AsyncConnection.connect(DB_URL, autocommit=False)
    yield c
    await c.rollback()
    await c.close()


@pytest_asyncio.fixture
async def campaign_id(conn):
    """Insert a test campaign, return UUID string. Edition=2014, massive_damage on."""
    settings = json.dumps({"monster_hp_mode": "average", "massive_damage": True})
    cur = await conn.execute(
        "INSERT INTO campaigns (name, edition, settings) VALUES (%s, %s, %s::jsonb) RETURNING id",
        ("Test Campaign", "2014", settings),
    )
    row = await cur.fetchone()
    cid = str(row[0])
    os.environ["DEFAULT_CAMPAIGN_ID"] = cid
    return cid


@pytest_asyncio.fixture
async def character_id(conn, campaign_id):
    """Insert a basic PC, return UUID string. 30 HP, Monk 5, no slots spent."""
    cur = await conn.execute(
        """
        INSERT INTO characters (
            campaign_id, player_name, name, level, class_summary, ac, max_hp, hp, temp_hp,
            speed, abilities, saves, skills, spell_slots, hit_dice, resources, death_saves,
            resistances, immunities, vulnerabilities, conditions, inventory
        ) VALUES (
            %s, 'Jeff', 'Kira', 5, 'Monk 5', 16, 30, 30, 0,
            30,
            '{"str":10,"dex":14,"con":12,"int":8,"wis":13,"cha":10}'::jsonb,
            '{"str":false,"dex":true,"con":false,"int":false,"wis":true,"cha":false}'::jsonb,
            '{}'::jsonb,
            '{"1":{"max":4,"used":0},"2":{"max":2,"used":0}}'::jsonb,
            '{"d8":{"max":5,"used":0}}'::jsonb,
            '{"ki":{"max":5,"used":0,"recharge":"short"}}'::jsonb,
            '{"successes":0,"failures":0}'::jsonb,
            '{}', '{}', '{}', '{}', '[]'::jsonb
        ) RETURNING id
        """,
        (campaign_id,),
    )
    row = await cur.fetchone()
    return str(row[0])


@pytest_asyncio.fixture
async def session_id(conn, campaign_id):
    """Insert an open session, return UUID string."""
    cur = await conn.execute(
        "INSERT INTO sessions (campaign_id, number) VALUES (%s, 1) RETURNING id",
        (campaign_id,),
    )
    row = await cur.fetchone()
    return str(row[0])
