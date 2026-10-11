"""D&D Beyond import MCP tool.

Primary path: scripts/import_ddb.py from a laptop (datacenter IPs often blocked).
This tool is a convenience that may fail at the fetch stage.
"""

from __future__ import annotations

from tools._util import resolve_campaign_id, get_active_session_id
from db import repo


async def import_ddb_character(
    url_or_id: str,
    player_name: str,
    reset_live_state: bool = False,
    campaign_id: str | None = None,
) -> dict:
    """Import or re-import a D&D Beyond character. Character must be set to Public.

    If the fetch is blocked (common from cloud IPs), returns an error with hint.
    Primary path: run scripts/import_ddb.py from a laptop instead.
    """
    from ddb.client import extract_id, fetch_character, DDBError
    from ddb.importer import import_character

    try:
        char_id = extract_id(url_or_id)
    except DDBError as e:
        return {
            "error": str(e),
            "hint": "run scripts/import_ddb.py from a laptop",
        }

    try:
        snapshot = await fetch_character(char_id)
    except DDBError as e:
        return {
            "error": f"DDB fetch blocked or failed: {e}",
            "hint": "run scripts/import_ddb.py from a laptop (datacenter IPs often blocked)",
        }

    cid = resolve_campaign_id(campaign_id)
    async with repo.tx() as conn:
        session_id = await get_active_session_id(conn, cid)
        return await import_character(
            conn, cid, snapshot, player_name,
            session_id=session_id,
            reset_live_state=reset_live_state,
        )
