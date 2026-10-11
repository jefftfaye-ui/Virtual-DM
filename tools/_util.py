"""Shared tool helpers — campaign_id resolution, event writing, UUID serialization."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from db import repo


def resolve_campaign_id(explicit: str | None) -> str:
    if explicit:
        return explicit
    cid = os.environ.get("DEFAULT_CAMPAIGN_ID")
    if not cid:
        raise RuntimeError("no campaign_id supplied and DEFAULT_CAMPAIGN_ID unset")
    return cid


def to_str(v: Any) -> Any:
    """Recursively convert uuid.UUID → str so JSON serialization works."""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, dict):
        return {k: to_str(vv) for k, vv in v.items()}
    if isinstance(v, list):
        return [to_str(i) for i in v]
    return v


async def write_event(
    conn,
    campaign_id: str,
    type_: str,
    payload: dict,
    reason: str,
    *,
    session_id: str | None = None,
    out_of_session: bool = False,
    compensates_event_id: str | None = None,
) -> str:
    row = await repo.fetchone(
        conn,
        """
        INSERT INTO events (campaign_id, session_id, type, payload, reason,
                            out_of_session, compensates_event_id)
        VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
        RETURNING id
        """,
        (
            campaign_id,
            session_id,
            type_,
            json.dumps(to_str(payload)),
            reason,
            out_of_session,
            compensates_event_id,
        ),
    )
    return str(row["id"])


async def get_campaign(conn, campaign_id: str) -> dict | None:
    return await repo.fetchone(
        conn,
        "SELECT * FROM campaigns WHERE id = %s",
        (campaign_id,),
    )


async def get_active_session_id(conn, campaign_id: str) -> str | None:
    row = await repo.fetchone(
        conn,
        "SELECT id FROM sessions WHERE campaign_id = %s AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
        (campaign_id,),
    )
    return str(row["id"]) if row else None
