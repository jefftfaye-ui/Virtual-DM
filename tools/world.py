"""World tools: NPCs, locations, secrets, quests, clocks, lore.

12 tools total. All follow _impl(conn, ...) pattern for testability.
Secrets: scoped-only — no tool ever returns all secrets for a campaign at once.
"""

from __future__ import annotations

import json
import re
from typing import Any

from db import repo
from tools._util import (
    resolve_campaign_id,
    to_str,
    write_event,
    get_active_session_id,
)


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


# ─── shared ───────────────────────────────────────────────────────────────────

def _str_id(v: Any) -> str | None:
    return str(v) if v is not None else None


async def _resolve_by_name_or_id(conn, table: str, name_or_id: str, campaign_id: str) -> dict | None:
    """Try UUID lookup first, then case-insensitive name."""
    assert table in {"npcs", "locations"}, f"invalid table: {table}"
    if _UUID_RE.match(name_or_id.strip()):
        return await repo.fetchone(
            conn,
            f"SELECT * FROM {table} WHERE id = %s AND campaign_id = %s",
            (name_or_id.strip(), campaign_id),
        )
    # Name match — fail if ambiguous
    rows = await repo.fetchall(
        conn,
        f"SELECT * FROM {table} WHERE campaign_id = %s AND lower(trim(name)) = lower(trim(%s))",
        (campaign_id, name_or_id),
    )
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        return {"_ambiguous": True, "matches": [r["name"] for r in rows]}
    return None


# ─── P4.1: upsert_npc / get_npc ───────────────────────────────────────────────

async def _upsert_npc_impl(
    conn,
    name: str,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
    *,
    id: str | None = None,
    role: str | None = None,
    location_id: str | None = None,
    disposition: int = 0,
    wants: str | None = None,
    fears: str | None = None,
    knows: str | None = None,
    public_description: str | None = None,
    status: str = "alive",
    notes: str | None = None,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    if id:
        row = await repo.fetchone(
            conn,
            """
            INSERT INTO npcs (id, campaign_id, name, role, location_id, disposition,
                wants, fears, knows, public_description, status, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, role=EXCLUDED.role, location_id=EXCLUDED.location_id,
                disposition=EXCLUDED.disposition, wants=EXCLUDED.wants, fears=EXCLUDED.fears,
                knows=EXCLUDED.knows, public_description=EXCLUDED.public_description,
                status=EXCLUDED.status, notes=EXCLUDED.notes
            RETURNING id
            """,
            (id, campaign_id, name, role, location_id, disposition,
             wants, fears, knows, public_description, status, notes),
        )
    else:
        row = await repo.fetchone(
            conn,
            """
            INSERT INTO npcs (campaign_id, name, role, location_id, disposition,
                wants, fears, knows, public_description, status, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (campaign_id, name, role, location_id, disposition,
             wants, fears, knows, public_description, status, notes),
        )

    npc_id = str(row["id"])
    await write_event(conn, campaign_id, "upsert_npc",
                      {"npc_id": npc_id, "name": name}, reason, session_id=session_id)
    result = {"npc_id": npc_id, "name": name}
    await repo.store_idempotent(conn, campaign_id, request_id, result)
    return result


async def upsert_npc(
    name: str,
    reason: str,
    id: str | None = None,
    role: str | None = None,
    location_id: str | None = None,
    disposition: int = 0,
    wants: str | None = None,
    fears: str | None = None,
    knows: str | None = None,
    public_description: str | None = None,
    status: str = "alive",
    notes: str | None = None,
    campaign_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Create or update an NPC. disposition: -3 (hostile) to +3 (friendly).
    knows is DM-only — never returned by default get_npc."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _upsert_npc_impl(
            conn, name, reason, cid, session_id, request_id,
            id=id, role=role, location_id=location_id, disposition=disposition,
            wants=wants, fears=fears, knows=knows,
            public_description=public_description, status=status, notes=notes,
        )


async def _get_npc_impl(conn, name_or_id: str, campaign_id: str, dm_view: bool) -> dict:
    row = await _resolve_by_name_or_id(conn, "npcs", name_or_id, campaign_id)
    if row is None:
        return {"error": f"NPC not found: {name_or_id}"}
    if row.get("_ambiguous"):
        return {"error": f"ambiguous NPC name '{name_or_id}'", "matches": row["matches"],
                "hint": "use the NPC's UUID instead"}

    loc_name = None
    if row.get("location_id"):
        loc = await repo.fetchone(conn, "SELECT name FROM locations WHERE id=%s", (row["location_id"],))
        loc_name = loc["name"] if loc else None

    result: dict[str, Any] = {
        "id": str(row["id"]),
        "name": row["name"],
        "role": row.get("role"),
        "location": loc_name,
        "disposition": row["disposition"],
        "wants": row.get("wants"),
        "fears": row.get("fears"),
        "public_description": row.get("public_description"),
        "status": row["status"],
    }
    if dm_view:
        result["knows"] = row.get("knows")

    # Never return linked secrets here — use get_secrets
    return result


async def get_npc(
    name_or_id: str,
    dm_view: bool = False,
    campaign_id: str | None = None,
) -> dict:
    """Get NPC. Default omits knows (DM-only). dm_view=true includes knows.
    Secrets are never returned here — use get_secrets."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        return await _get_npc_impl(conn, name_or_id, cid, dm_view)


# ─── P4.2: upsert_location / get_location ─────────────────────────────────────

async def _upsert_location_impl(
    conn,
    name: str,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
    *,
    id: str | None = None,
    region: str | None = None,
    description: str | None = None,
    notes: str | None = None,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    if id:
        row = await repo.fetchone(
            conn,
            """
            INSERT INTO locations (id, campaign_id, name, region, description, notes)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, region=EXCLUDED.region,
                description=EXCLUDED.description, notes=EXCLUDED.notes
            RETURNING id
            """,
            (id, campaign_id, name, region, description, notes),
        )
    else:
        row = await repo.fetchone(
            conn,
            "INSERT INTO locations (campaign_id, name, region, description, notes) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (campaign_id, name, region, description, notes),
        )

    loc_id = str(row["id"])
    await write_event(conn, campaign_id, "upsert_location",
                      {"location_id": loc_id, "name": name}, reason, session_id=session_id)
    result = {"location_id": loc_id, "name": name}
    await repo.store_idempotent(conn, campaign_id, request_id, result)
    return result


async def upsert_location(
    name: str,
    reason: str,
    id: str | None = None,
    region: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    campaign_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Create or update a location."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _upsert_location_impl(
            conn, name, reason, cid, session_id, request_id,
            id=id, region=region, description=description, notes=notes,
        )


async def _get_location_impl(conn, name_or_id: str, campaign_id: str) -> dict:
    row = await _resolve_by_name_or_id(conn, "locations", name_or_id, campaign_id)
    if row is None:
        return {"error": f"location not found: {name_or_id}"}
    if row.get("_ambiguous"):
        return {"error": f"ambiguous location name '{name_or_id}'", "matches": row["matches"],
                "hint": "use UUID instead"}
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "region": row.get("region"),
        "description": row.get("description"),
        "notes": row.get("notes"),
    }


async def get_location(name_or_id: str, campaign_id: str | None = None) -> dict:
    """Get a location by name or UUID."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        return await _get_location_impl(conn, name_or_id, cid)


# ─── P4.3: secrets ────────────────────────────────────────────────────────────

async def _add_secret_impl(
    conn,
    text: str,
    tied_to_type: str,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
    tied_to_id: str | None = None,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    if tied_to_type not in ("npc", "location", "quest", "none"):
        return {"error": f"tied_to_type must be npc/location/quest/none, got {tied_to_type!r}"}

    row = await repo.fetchone(
        conn,
        "INSERT INTO secrets (campaign_id, text, tied_to_type, tied_to_id) "
        "VALUES (%s,%s,%s,%s) RETURNING id",
        (campaign_id, text, tied_to_type, tied_to_id),
    )
    secret_id = str(row["id"])
    await write_event(conn, campaign_id, "add_secret",
                      {"secret_id": secret_id, "tied_to_type": tied_to_type, "tied_to_id": tied_to_id},
                      reason, session_id=session_id)
    result = {"secret_id": secret_id, "tied_to_type": tied_to_type}
    await repo.store_idempotent(conn, campaign_id, request_id, result)
    return result


async def add_secret(
    text: str,
    tied_to_type: str,
    reason: str,
    tied_to_id: str | None = None,
    campaign_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Record a secret scoped to an NPC, location, quest, or none. Never list-all."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _add_secret_impl(conn, text, tied_to_type, reason, cid, session_id, request_id,
                                      tied_to_id=tied_to_id)


async def _get_secrets_impl(
    conn,
    tied_to_type: str,
    campaign_id: str,
    tied_to_id: str | None,
) -> dict:
    # Deliberately require scope — no list-all
    if tied_to_type not in ("npc", "location", "quest", "none"):
        return {"error": f"tied_to_type must be npc/location/quest/none"}

    rows = await repo.fetchall(
        conn,
        "SELECT id, text, tied_to_type, tied_to_id, revealed, revealed_at, revealed_how "
        "FROM secrets WHERE campaign_id=%s AND tied_to_type=%s AND (tied_to_id=%s OR (%s IS NULL AND tied_to_id IS NULL)) "
        "ORDER BY created_at",
        (campaign_id, tied_to_type, tied_to_id, tied_to_id),
    )
    return {
        "secrets": [
            {
                "id": str(r["id"]),
                "text": r["text"],
                "revealed": r["revealed"],
                "revealed_how": r.get("revealed_how"),
            }
            for r in rows
        ],
        "tied_to_type": tied_to_type,
        "tied_to_id": _str_id(tied_to_id),
    }


async def get_secrets(
    tied_to_type: str,
    tied_to_id: str | None = None,
    campaign_id: str | None = None,
) -> dict:
    """Get secrets scoped to a specific entity. No list-all — tied_to_type required."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        return await _get_secrets_impl(conn, tied_to_type, cid, tied_to_id)


async def _reveal_secret_impl(
    conn,
    secret_id: str,
    how: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    row = await repo.fetchone(
        conn, "SELECT id, text, revealed FROM secrets WHERE id=%s AND campaign_id=%s",
        (secret_id, campaign_id),
    )
    if not row:
        return {"error": "secret not found", "hint": f"id={secret_id}"}

    await repo.execute(
        conn,
        "UPDATE secrets SET revealed=true, revealed_at=now(), revealed_how=%s WHERE id=%s",
        (how, secret_id),
    )
    await write_event(conn, campaign_id, "reveal_secret",
                      {"secret_id": secret_id, "how": how}, f"secret revealed: {how}",
                      session_id=session_id)
    result = {"secret_id": secret_id, "revealed": True, "how": how}
    await repo.store_idempotent(conn, campaign_id, request_id, result)
    return result


async def reveal_secret(
    secret_id: str,
    how: str,
    campaign_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Mark a secret as revealed and record how the players learned it."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _reveal_secret_impl(conn, secret_id, how, cid, session_id, request_id)


# ─── P4.4: quests + clocks ────────────────────────────────────────────────────

async def _upsert_quest_impl(
    conn,
    title: str,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
    *,
    id: str | None = None,
    status: str = "rumor",
    summary: str | None = None,
    giver_npc_id: str | None = None,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    if status not in ("rumor", "active", "done", "failed"):
        return {"error": f"status must be rumor/active/done/failed, got {status!r}"}

    if id:
        row = await repo.fetchone(
            conn,
            """
            INSERT INTO quests (id, campaign_id, title, status, summary, giver_npc_id)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                title=EXCLUDED.title, status=EXCLUDED.status,
                summary=EXCLUDED.summary, giver_npc_id=EXCLUDED.giver_npc_id
            RETURNING id
            """,
            (id, campaign_id, title, status, summary, giver_npc_id),
        )
    else:
        row = await repo.fetchone(
            conn,
            "INSERT INTO quests (campaign_id, title, status, summary, giver_npc_id) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (campaign_id, title, status, summary, giver_npc_id),
        )

    quest_id = str(row["id"])
    await write_event(conn, campaign_id, "upsert_quest",
                      {"quest_id": quest_id, "title": title, "status": status},
                      reason, session_id=session_id)
    result = {"quest_id": quest_id, "title": title, "status": status}
    await repo.store_idempotent(conn, campaign_id, request_id, result)
    return result


async def upsert_quest(
    title: str,
    reason: str,
    id: str | None = None,
    status: str = "rumor",
    summary: str | None = None,
    giver_npc_id: str | None = None,
    campaign_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Create or update a quest. status: rumor | active | done | failed."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _upsert_quest_impl(
            conn, title, reason, cid, session_id, request_id,
            id=id, status=status, summary=summary, giver_npc_id=giver_npc_id,
        )


async def _upsert_clock_impl(
    conn,
    name: str,
    segments: int,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
    *,
    id: str | None = None,
    filled: int = 0,
    consequence: str | None = None,
    visible: bool = True,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    if segments < 1:
        return {"error": "segments must be >= 1"}
    filled = max(0, min(filled, segments))

    if id:
        row = await repo.fetchone(
            conn,
            """
            INSERT INTO clocks (id, campaign_id, name, segments, filled, consequence, visible)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, segments=EXCLUDED.segments, filled=EXCLUDED.filled,
                consequence=EXCLUDED.consequence, visible=EXCLUDED.visible
            RETURNING id
            """,
            (id, campaign_id, name, segments, filled, consequence, visible),
        )
    else:
        row = await repo.fetchone(
            conn,
            "INSERT INTO clocks (campaign_id, name, segments, filled, consequence, visible) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (campaign_id, name, segments, filled, consequence, visible),
        )

    clock_id = str(row["id"])
    await write_event(conn, campaign_id, "upsert_clock",
                      {"clock_id": clock_id, "name": name, "segments": segments},
                      reason, session_id=session_id)
    result = {"clock_id": clock_id, "name": name, "filled": filled, "segments": segments}
    await repo.store_idempotent(conn, campaign_id, request_id, result)
    return result


async def upsert_clock(
    name: str,
    segments: int,
    reason: str,
    id: str | None = None,
    filled: int = 0,
    consequence: str | None = None,
    visible: bool = True,
    campaign_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Create or update a progress clock. visible=false hides it from players."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _upsert_clock_impl(
            conn, name, segments, reason, cid, session_id, request_id,
            id=id, filled=filled, consequence=consequence, visible=visible,
        )


async def _tick_clock_impl(
    conn,
    clock_id: str,
    segments: int,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    row = await repo.fetchone(
        conn,
        "SELECT * FROM clocks WHERE id=%s AND campaign_id=%s FOR UPDATE",
        (clock_id, campaign_id),
    )
    if not row:
        return {"error": "clock not found", "hint": f"id={clock_id}"}

    prev_filled = row["filled"]
    new_filled = min(row["segments"], prev_filled + segments)

    await repo.execute(
        conn, "UPDATE clocks SET filled=%s WHERE id=%s", (new_filled, clock_id)
    )

    just_filled = new_filled == row["segments"] and prev_filled < row["segments"]

    await write_event(
        conn, campaign_id, "tick_clock",
        {"clock_id": clock_id, "prev_filled": prev_filled, "new_filled": new_filled,
         "segments": row["segments"], "filled": just_filled},
        reason, session_id=session_id,
    )

    result: dict[str, Any] = {
        "clock_id": clock_id,
        "name": row["name"],
        "filled": new_filled,
        "segments": row["segments"],
        "progress": f"{new_filled}/{row['segments']}",
        "filled_now": just_filled,
    }
    if just_filled:
        # Consequence revealed only on fill — regardless of visibility setting
        result["consequence"] = row.get("consequence")

    await repo.store_idempotent(conn, campaign_id, request_id, result)
    return result


async def tick_clock(
    clock_id: str,
    segments: int = 1,
    reason: str = "ticked",
    campaign_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Advance a clock by N segments. Returns consequence only when clock fills."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _tick_clock_impl(conn, clock_id, segments, reason, cid, session_id, request_id)


# ─── P4.5: lore ───────────────────────────────────────────────────────────────

async def _upsert_lore_impl(
    conn,
    title: str,
    body: str,
    tags: list[str],
    dm_only: bool,
    reason: str,
    campaign_id: str,
    session_id: str | None,
    request_id: str | None,
    *,
    id: str | None = None,
) -> dict:
    prior = await repo.check_idempotent(conn, campaign_id, request_id)
    if prior is not None:
        return prior

    if id:
        row = await repo.fetchone(
            conn,
            """
            INSERT INTO lore (id, campaign_id, title, body, tags, dm_only)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                title=EXCLUDED.title, body=EXCLUDED.body,
                tags=EXCLUDED.tags, dm_only=EXCLUDED.dm_only
            RETURNING id
            """,
            (id, campaign_id, title, body, tags, dm_only),
        )
    else:
        row = await repo.fetchone(
            conn,
            "INSERT INTO lore (campaign_id, title, body, tags, dm_only) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (campaign_id, title, body, tags, dm_only),
        )

    lore_id = str(row["id"])
    await write_event(conn, campaign_id, "upsert_lore",
                      {"lore_id": lore_id, "title": title, "dm_only": dm_only},
                      reason, session_id=session_id)
    result = {"lore_id": lore_id, "title": title, "dm_only": dm_only}
    await repo.store_idempotent(conn, campaign_id, request_id, result)
    return result


async def upsert_lore(
    title: str,
    body: str,
    reason: str,
    tags: list[str] | None = None,
    dm_only: bool = False,
    id: str | None = None,
    campaign_id: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Create or update a lore entry. dm_only=true marks it for DM use only."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await _upsert_lore_impl(
            conn, title, body, tags or [], dm_only, reason, cid, session_id, request_id, id=id
        )


async def _get_lore_impl(conn, query: str, campaign_id: str) -> dict:
    # Three-stage: exact title match, then FTS
    exact = await repo.fetchall(
        conn,
        "SELECT id, title, body, tags, dm_only FROM lore "
        "WHERE campaign_id=%s AND lower(trim(title)) = lower(trim(%s))",
        (campaign_id, query),
    )
    if exact:
        rows = exact
    else:
        rows = await repo.fetchall(
            conn,
            """
            SELECT id, title, body, tags, dm_only,
                   ts_rank(tsv, websearch_to_tsquery('english', %s)) AS rank
            FROM lore
            WHERE campaign_id=%s AND tsv @@ websearch_to_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT 5
            """,
            (query, campaign_id, query),
        )

    return {
        "results": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "body": r["body"],
                "tags": list(r.get("tags") or []),
                "dm_only": r["dm_only"],
            }
            for r in rows
        ]
    }


async def get_lore(query: str, campaign_id: str | None = None) -> dict:
    """Full-text search over lore. Returns dm_only entries flagged — DM narrates only public ones."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        return await _get_lore_impl(conn, query, cid)
