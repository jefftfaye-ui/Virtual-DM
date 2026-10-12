"""Session tools: start_session, end_session, get_recent_events."""

from __future__ import annotations

from db import repo
from tools._util import resolve_campaign_id, to_str, write_event
from tools.state import _get_state_impl


async def _start_session_impl(conn, campaign_id: str) -> dict:
    # next session number
    row = await repo.fetchone(
        conn,
        "SELECT COALESCE(MAX(number), 0) + 1 AS next FROM sessions WHERE campaign_id = %s",
        (campaign_id,),
    )
    next_num = row["next"]

    # close any unclosed sessions (shouldn't happen but be safe)
    await repo.execute(
        conn,
        "UPDATE sessions SET ended_at = now() WHERE campaign_id = %s AND ended_at IS NULL",
        (campaign_id,),
    )

    # last 2 recaps
    recaps_rows = await repo.fetchall(
        conn,
        "SELECT number, recap FROM sessions WHERE campaign_id = %s AND recap IS NOT NULL "
        "ORDER BY number DESC LIMIT 2",
        (campaign_id,),
    )
    recent_recaps = [{"number": r["number"], "recap": r["recap"]} for r in recaps_rows]

    sess_row = await repo.fetchone(
        conn,
        "INSERT INTO sessions (campaign_id, number) VALUES (%s, %s) RETURNING id",
        (campaign_id, next_num),
    )
    session_id = str(sess_row["id"])

    # Backfill any messages saved this turn before session was created
    await repo.execute(
        conn,
        "UPDATE messages SET session_id = %s WHERE campaign_id = %s AND session_id IS NULL",
        (session_id, campaign_id),
    )

    await write_event(
        conn, campaign_id, "session_start",
        {"session_id": session_id, "number": next_num},
        "session started",
        session_id=session_id,
    )

    state = await _get_state_impl(conn, campaign_id, ["party", "scene", "encounter", "quests", "clocks"])

    return to_str({
        "session_id": session_id,
        "number": next_num,
        "recent_recaps": recent_recaps,
        "state": state,
    })


async def start_session(campaign_id: str | None = None) -> dict:
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        return await _start_session_impl(conn, cid)


async def _end_session_impl(conn, recap: str, campaign_id: str) -> dict:
    sess = await repo.fetchone(
        conn,
        "SELECT id, number FROM sessions WHERE campaign_id = %s AND ended_at IS NULL "
        "ORDER BY started_at DESC LIMIT 1",
        (campaign_id,),
    )
    if not sess:
        return {"error": "no active session", "hint": "call start_session first"}

    await repo.execute(
        conn,
        "UPDATE sessions SET ended_at = now(), recap = %s WHERE id = %s",
        (recap, sess["id"]),
    )

    await write_event(
        conn, campaign_id, "session_end",
        {"session_id": str(sess["id"]), "number": sess["number"]},
        "session ended",
        session_id=str(sess["id"]),
    )

    return {"session_id": str(sess["id"]), "number": sess["number"]}


async def end_session(recap: str, campaign_id: str | None = None) -> dict:
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        return await _end_session_impl(conn, recap, cid)


async def get_recent_events(n: int = 20, campaign_id: str | None = None) -> dict:
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        rows = await repo.fetchall(
            conn,
            "SELECT id, type, reason, created_at FROM events "
            "WHERE campaign_id = %s ORDER BY created_at DESC LIMIT %s",
            (cid, min(n, 100)),
        )
    return to_str({
        "events": [
            {
                "id": str(r["id"]),
                "type": r["type"],
                "reason": r["reason"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]
    })
