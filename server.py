"""FastMCP app — AI DM server.

MVP auth: unguessable URL path (`/mcp/{CONNECTOR_SECRET}`). Known limitation
(SPEC §1): the secret leaks to platform access logs. Rotate periodically.

Transport: streamable HTTP, stateless. Keep responses small per SPEC §4.6.
"""

from __future__ import annotations

import os
from typing import Literal

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from tools import combat as t_combat
from tools import dice as t_dice
from tools import ddb_tool as t_ddb
from tools import rules as t_rules
from tools import sessions as t_sessions
from tools import state as t_state
from tools import world as t_world

load_dotenv()

CONNECTOR_SECRET = os.environ.get("CONNECTOR_SECRET")
if not CONNECTOR_SECRET or len(CONNECTOR_SECRET) < 24:
    raise RuntimeError(
        "CONNECTOR_SECRET must be set and ≥24 chars (URL-safe, ≥32 random bytes recommended)."
    )

MOUNT_PATH = f"/mcp/{CONNECTOR_SECRET}"

mcp = FastMCP("dm-server", stateless_http=True)

# ─── Dice (2) ──────────────────────────────────────────────────────────
Mode = Literal["normal", "advantage", "disadvantage"]
Visibility = Literal["public", "secret"]


@mcp.tool()
async def roll(
    expression: str,
    reason: str,
    actor: str,
    mode: Mode = "normal",
    dc: int | None = None,
    visibility: Visibility = "public",
    campaign_id: str | None = None,
    session_id: str | None = None,
    encounter_id: str | None = None,
) -> dict:
    """Roll dice server-side. Secret rolls return only outcome + margin band."""
    return await t_dice.roll(
        expression, reason, actor,
        mode=mode, dc=dc, visibility=visibility,
        campaign_id=campaign_id, session_id=session_id, encounter_id=encounter_id,
    )


@mcp.tool()
async def record_player_roll(
    actor: str,
    reason: str,
    total: int,
    natural: int | None = None,
    dc: int | None = None,
    campaign_id: str | None = None,
    session_id: str | None = None,
    encounter_id: str | None = None,
) -> dict:
    """Record a roll the player made physically / in DDB."""
    return await t_dice.record_player_roll(
        actor, reason, total,
        natural=natural, dc=dc,
        campaign_id=campaign_id, session_id=session_id, encounter_id=encounter_id,
    )


# ─── State (6) — Phase 2 ───────────────────────────────────────────────
mcp.tool()(t_state.get_state)
mcp.tool()(t_state.update_character)
mcp.tool()(t_state.death_save)
mcp.tool()(t_state.rest)
mcp.tool()(t_state.set_scene)
mcp.tool()(t_state.undo_last_event)

# ─── Combat (5) — Phase 3 ──────────────────────────────────────────────
mcp.tool()(t_combat.start_encounter)
mcp.tool()(t_combat.add_combatant)
mcp.tool()(t_combat.update_combatant)
mcp.tool()(t_combat.next_turn)
mcp.tool()(t_combat.end_encounter)

# ─── World (12) — Phase 4 ──────────────────────────────────────────────
mcp.tool()(t_world.upsert_npc)
mcp.tool()(t_world.get_npc)
mcp.tool()(t_world.upsert_location)
mcp.tool()(t_world.get_location)
mcp.tool()(t_world.add_secret)
mcp.tool()(t_world.get_secrets)
mcp.tool()(t_world.reveal_secret)
mcp.tool()(t_world.upsert_quest)
mcp.tool()(t_world.upsert_clock)
mcp.tool()(t_world.tick_clock)
mcp.tool()(t_world.upsert_lore)
mcp.tool()(t_world.get_lore)

# ─── Rules (2) — Phase 5 ───────────────────────────────────────────────
mcp.tool()(t_rules.lookup_rule)
mcp.tool()(t_rules.lookup_monster)

# ─── DDB (1) — Phase 6 ─────────────────────────────────────────────────
mcp.tool()(t_ddb.import_ddb_character)

# ─── Sessions (3) — Phase 2 ────────────────────────────────────────────
mcp.tool()(t_sessions.start_session)
mcp.tool()(t_sessions.end_session)
mcp.tool()(t_sessions.get_recent_events)

# Total: 2 + 6 + 5 + 12 + 2 + 1 + 3 = 31 tools (SPEC §3)


def main() -> None:
    import uvicorn

    app = mcp.streamable_http_app()

    # Wrap to reject anything not under MOUNT_PATH.
    orig_app = app

    async def gated(scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if not path.startswith(MOUNT_PATH):
                await send({"type": "http.response.start", "status": 404, "headers": []})
                await send({"type": "http.response.body", "body": b"not found"})
                return
            # strip the secret prefix so the inner app sees "/"
            scope = dict(scope)
            scope["path"] = path[len(MOUNT_PATH):] or "/"
            scope["raw_path"] = scope["path"].encode()
        await orig_app(scope, receive, send)

    uvicorn.run(gated, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


if __name__ == "__main__":
    main()
