"""Dice tools: roll, record_player_roll. Writes to `rolls` table."""

from __future__ import annotations

import json
import os
from typing import Literal

from db import repo
from dice.parser import DiceError, RollResult, roll as roll_expr
from tools._util import resolve_campaign_id

Mode = Literal["normal", "advantage", "disadvantage"]
Visibility = Literal["public", "secret"]


def _outcome(total: int, natural: int | None, dc: int | None) -> dict | None:
    if dc is None:
        return None
    return {
        "success": total >= dc,
        "nat20": natural == 20,
        "nat1": natural == 1,
    }


def _margin_band(total: int, dc: int) -> str:
    delta = total - dc
    if delta >= 5:
        return "by 5+"
    if delta >= 0:
        return "by 1-4"
    if delta >= -4:
        return "miss by 1-4"
    return "miss by 5+"


async def _roll_impl(
    conn,
    expression: str,
    reason: str,
    actor: str,
    campaign_id: str,
    *,
    mode: Mode = "normal",
    dc: int | None = None,
    visibility: Visibility = "public",
    session_id: str | None = None,
    encounter_id: str | None = None,
) -> dict:
    """Roll + persist within a caller-supplied connection. Call this from other tools."""
    if visibility == "secret" and dc is None:
        return {"error": "visibility='secret' requires a dc", "hint": "pass dc=…"}

    try:
        result: RollResult = roll_expr(expression, mode=mode)
    except DiceError as e:
        return {"error": str(e), "hint": "see dice/parser.py grammar"}

    outcome = _outcome(result.total, result.natural, dc)
    outcome_str = "success" if outcome and outcome["success"] else "failure" if outcome else None

    row = await repo.fetchone(
        conn,
        """
        INSERT INTO rolls (
            campaign_id, session_id, encounter_id, actor, reason, expression, mode,
            source, natural, dice, modifier, total, visibility, dc, outcome
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,'server',%s,%s::jsonb,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (
            campaign_id, session_id, encounter_id, actor, reason, expression, result.mode,
            result.natural, json.dumps(result.terms), result.modifier, result.total,
            visibility, dc, outcome_str,
        ),
    )

    if visibility == "secret":
        return {
            "roll_id": str(row["id"]),
            "outcome": outcome_str,
            "margin_band": _margin_band(result.total, dc) if dc is not None else None,
        }

    return {
        "roll_id": str(row["id"]),
        "dice": result.dice,
        "kept": result.kept,
        "modifier": result.modifier,
        "total": result.total,
        "natural": result.natural,
        "mode": result.mode,
        "outcome": outcome,
    }


async def roll(
    expression: str,
    reason: str,
    actor: str,
    *,
    mode: Mode = "normal",
    dc: int | None = None,
    visibility: Visibility = "public",
    campaign_id: str | None = None,
    session_id: str | None = None,
    encounter_id: str | None = None,
) -> dict:
    """MCP tool: roll dice server-side. Secret rolls return only outcome + margin band."""
    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        return await _roll_impl(
            conn, expression, reason, actor, cid,
            mode=mode, dc=dc, visibility=visibility,
            session_id=session_id, encounter_id=encounter_id,
        )


async def record_player_roll(
    actor: str,
    reason: str,
    total: int,
    *,
    natural: int | None = None,
    dc: int | None = None,
    campaign_id: str | None = None,
    session_id: str | None = None,
    encounter_id: str | None = None,
) -> dict:
    """MCP tool: record a roll the player made physically or in DDB."""
    cid = resolve_campaign_id(campaign_id)
    outcome_str = None
    if dc is not None:
        outcome_str = "success" if total >= dc else "failure"
    async with repo.tx() as conn:
        row = await repo.fetchone(
            conn,
            """
            INSERT INTO rolls (
                campaign_id, session_id, encounter_id, actor, reason, expression, mode,
                source, natural, dice, modifier, total, visibility, dc, outcome
            )
            VALUES (%s,%s,%s,%s,%s,'player-reported','normal','player',%s,'[]'::jsonb,0,%s,'public',%s,%s)
            RETURNING id
            """,
            (cid, session_id, encounter_id, actor, reason, natural, total, dc, outcome_str),
        )
    return {"roll_id": str(row["id"]), "total": total, "outcome": outcome_str}
