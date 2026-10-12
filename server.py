"""FastMCP app — AI DM server, plus web UI endpoints.

Routes:
  /ui                     player interface (HTML)
  /api/state              party state JSON
  /api/chat               SSE streaming chat (Claude + tool loop)
  /mcp/{CONNECTOR_SECRET} MCP endpoint for claude.ai custom connector
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

import anthropic
import openai as _openai
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response, StreamingResponse
from starlette.routing import Mount, Route

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

# ─── MCP server (31 tools) ────────────────────────────────────────────────────

mcp = FastMCP("dm-server", stateless_http=True)

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


mcp.tool()(t_state.get_state)
mcp.tool()(t_state.update_character)
mcp.tool()(t_state.death_save)
mcp.tool()(t_state.rest)
mcp.tool()(t_state.set_scene)
mcp.tool()(t_state.undo_last_event)
mcp.tool()(t_combat.start_encounter)
mcp.tool()(t_combat.add_combatant)
mcp.tool()(t_combat.update_combatant)
mcp.tool()(t_combat.next_turn)
mcp.tool()(t_combat.end_encounter)
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
mcp.tool()(t_rules.lookup_rule)
mcp.tool()(t_rules.lookup_monster)
mcp.tool()(t_ddb.import_ddb_character)
mcp.tool()(t_sessions.start_session)
mcp.tool()(t_sessions.end_session)
mcp.tool()(t_sessions.get_recent_events)

# Total: 31 tools


# ─── DM system prompt ─────────────────────────────────────────────────────────

_DM_SYSTEM = """You are the Dungeon Master for a D&D 5e campaign with two players: Jeff and Julee.

RULES:
1. Every player message begins with "Jeff:" or "Julee:". If unlabeled and the actor matters, ask.
2. If DM tools are unavailable, say so out of character immediately. Do not improvise mechanics.
3. Run all death saves with `death_save` — never with `roll`.
4. When a tool response includes `concentration_check`, resolve it before moving on.
5. For hidden checks, use `roll(visibility="secret", dc=…)` and narrate only from the outcome.
6. Use `get_npc(dm_view=true)` only when deciding what an NPC reveals or conceals.
7. Call `start_session` at the start of each session. Use `get_state` to reorient after confusion.
8. Never fabricate dice results, HP values, slot expenditures, or condition changes. All mechanics go through tools.

SCENE TOOL — IMPORTANT:
Call `set_scene` every time the party enters a new location or the scene meaningfully changes (a new room, outdoor area, building interior, etc.). The interface automatically generates a visual of the scene from your description — you do not need to produce images yourself and never need to mention images or visuals. Just call `set_scene` with a vivid description and the system handles the rest silently. Call it at session start too.

NARRATION:
Vivid, present-tense. Short action sentences. Describe consequences and set scenes — never narrate player actions for them. Leave space for decisions. Give every scene a sensory detail that grounds it."""


# ─── tool dispatch ────────────────────────────────────────────────────────────

_DISPATCH: dict = {
    "roll": t_dice.roll,
    "record_player_roll": t_dice.record_player_roll,
    "get_state": t_state.get_state,
    "update_character": t_state.update_character,
    "death_save": t_state.death_save,
    "rest": t_state.rest,
    "set_scene": t_state.set_scene,
    "undo_last_event": t_state.undo_last_event,
    "start_session": t_sessions.start_session,
    "end_session": t_sessions.end_session,
    "get_recent_events": t_sessions.get_recent_events,
    "start_encounter": t_combat.start_encounter,
    "add_combatant": t_combat.add_combatant,
    "update_combatant": t_combat.update_combatant,
    "next_turn": t_combat.next_turn,
    "end_encounter": t_combat.end_encounter,
    "upsert_npc": t_world.upsert_npc,
    "get_npc": t_world.get_npc,
    "upsert_location": t_world.upsert_location,
    "get_location": t_world.get_location,
    "add_secret": t_world.add_secret,
    "get_secrets": t_world.get_secrets,
    "reveal_secret": t_world.reveal_secret,
    "upsert_quest": t_world.upsert_quest,
    "upsert_clock": t_world.upsert_clock,
    "tick_clock": t_world.tick_clock,
    "upsert_lore": t_world.upsert_lore,
    "get_lore": t_world.get_lore,
    "lookup_rule": t_rules.lookup_rule,
    "lookup_monster": t_rules.lookup_monster,
    "import_ddb_character": t_ddb.import_ddb_character,
}


async def _call_tool(name: str, inputs: dict) -> dict:
    fn = _DISPATCH.get(name)
    if not fn:
        return {"error": f"unknown tool: {name}"}
    try:
        return await fn(**inputs)
    except TypeError as e:
        # Filter out unexpected kwargs before retrying
        import inspect
        sig = inspect.signature(fn)
        valid = {k: v for k, v in inputs.items() if k in sig.parameters}
        try:
            return await fn(**valid)
        except Exception as e2:
            return {"error": str(e2)}
    except Exception as e:
        return {"error": str(e)}


_TOOL_SCHEMAS: list | None = None


def _get_tool_schemas() -> list:
    global _TOOL_SCHEMAS
    if _TOOL_SCHEMAS is not None:
        return _TOOL_SCHEMAS
    schemas = []
    for name, tool in mcp._tool_manager._tools.items():
        params = getattr(tool, "parameters", None) or {"type": "object", "properties": {}}
        desc = (getattr(tool, "description", "") or "").strip()
        schemas.append({"name": name, "description": desc, "input_schema": params})
    _TOOL_SCHEMAS = schemas
    return schemas


# ─── UI handler ───────────────────────────────────────────────────────────────

async def campaigns_handler(request: Request) -> Response:
    try:
        from db import repo as _repo
        async with _repo.tx() as conn:
            rows = await _repo.fetchall(
                conn,
                "SELECT id, name, edition, current_scene FROM campaigns WHERE active=true ORDER BY created_at",
            )
        campaigns = [{"id": str(r["id"]), "name": r["name"], "edition": r["edition"], "scene": r.get("current_scene")} for r in rows]
        return Response(json.dumps(campaigns, default=str), media_type="application/json")
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), media_type="application/json", status_code=500)


async def messages_handler(request: Request) -> Response:
    """Return conversation history for a campaign (last 100 messages)."""
    cid = request.query_params.get("campaign_id") or os.environ.get("DEFAULT_CAMPAIGN_ID")
    session_id = request.query_params.get("session_id")
    if not cid:
        return Response(json.dumps({"error": "no campaign_id"}), media_type="application/json")
    try:
        from db import repo as _repo
        async with _repo.tx() as conn:
            if session_id:
                rows = await _repo.fetchall(
                    conn,
                    "SELECT role, content, speaker, created_at FROM messages "
                    "WHERE campaign_id=%s AND session_id=%s ORDER BY created_at LIMIT 200",
                    (cid, session_id),
                )
            else:
                # Get the most recent open session's messages
                rows = await _repo.fetchall(
                    conn,
                    "SELECT m.role, m.content, m.speaker, m.created_at FROM messages m "
                    "LEFT JOIN sessions s ON m.session_id = s.id "
                    "WHERE m.campaign_id=%s "
                    "ORDER BY m.created_at DESC LIMIT 100",
                    (cid,),
                )
                rows = list(reversed(rows))
        return Response(
            json.dumps([{"role": r["role"], "content": r["content"], "speaker": r.get("speaker"), "created_at": r["created_at"].isoformat() if r["created_at"] else None} for r in rows], default=str),
            media_type="application/json",
        )
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), media_type="application/json", status_code=500)


async def scene_image_handler(request: Request) -> Response:
    """Generate a DALL-E 3 scene image from a description."""
    try:
        body = await request.json()
    except Exception:
        return Response(json.dumps({"error": "invalid JSON"}), status_code=400, media_type="application/json")

    description = (body.get("description") or "").strip()
    location = (body.get("location") or "").strip()
    if not description and not location:
        return Response(json.dumps({"error": "description required"}), media_type="application/json", status_code=400)

    prompt = (
        f"Fantasy tabletop RPG environment illustration. "
        f"{'Location: ' + location + '. ' if location else ''}"
        f"{description} "
        f"Dark atmospheric oil painting style, cinematic lighting, rich detail, "
        f"no characters in foreground, no text, no UI elements, no watermarks."
    )[:900]  # DALL-E prompt limit

    try:
        client = _openai.AsyncOpenAI()
        resp = await client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1536x1024",  # landscape ~3:2, closest to 16:9 supported
            n=1,
        )
        img_data = resp.data[0]
        if getattr(img_data, "url", None):
            url = img_data.url
        elif getattr(img_data, "b64_json", None):
            url = f"data:image/png;base64,{img_data.b64_json}"
        else:
            return Response(json.dumps({"error": "no image returned"}), media_type="application/json", status_code=500)
        revised = getattr(img_data, "revised_prompt", None)
        return Response(json.dumps({"url": url, "revised_prompt": revised}), media_type="application/json")
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), media_type="application/json", status_code=500)


_SUMMARY_PROMPT = """You are summarizing a D&D session for a campaign journal. Write a concise summary (200-300 words) covering:
- Where the session started and ended (locations)
- Key NPCs met, their names and roles
- Major decisions the party made
- Rolls that mattered and outcomes
- Current party status (conditions, resources spent, quests active)
- The most important unresolved thread going into next session

Write in past tense, third person. Include NPC names, location names, and quest names exactly as they appeared. This summary will be fed to the DM AI at the start of the next session to restore context."""

async def generate_summary_handler(request: Request) -> Response:
    """Generate and store an AI summary of a session's messages."""
    try:
        body = await request.json()
    except Exception:
        return Response(json.dumps({"error": "invalid JSON"}), status_code=400, media_type="application/json")

    campaign_id = body.get("campaign_id") or os.environ.get("DEFAULT_CAMPAIGN_ID")
    session_id = body.get("session_id")
    if not campaign_id:
        return Response(json.dumps({"error": "campaign_id required"}), media_type="application/json", status_code=400)

    try:
        from db import repo as _repo
        async with _repo.tx() as conn:
            # Get session messages
            if session_id:
                rows = await _repo.fetchall(
                    conn,
                    "SELECT role, speaker, content FROM messages WHERE campaign_id=%s AND session_id=%s ORDER BY created_at",
                    (campaign_id, session_id),
                )
            else:
                rows = await _repo.fetchall(
                    conn,
                    "SELECT role, speaker, content FROM messages WHERE campaign_id=%s ORDER BY created_at",
                    (campaign_id,),
                )

            if not rows:
                return Response(json.dumps({"error": "no messages found"}), media_type="application/json", status_code=404)

            # Build transcript
            transcript = "\n\n".join(
                f"{'[' + r['speaker'] + ']' if r.get('speaker') else '[DM]'}: {r['content'][:500]}"
                for r in rows
            )[:15000]  # cap input

            # Summarize with Haiku (cheapest)
            ai = anthropic.AsyncAnthropic()
            resp = await ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=_SUMMARY_PROMPT,
                messages=[{"role": "user", "content": f"Session transcript:\n\n{transcript}"}],
            )
            summary = resp.content[0].text

            # Store
            if session_id:
                await _repo.execute(
                    conn,
                    "UPDATE sessions SET ai_summary=%s WHERE id=%s AND campaign_id=%s",
                    (summary, session_id, campaign_id),
                )
            return Response(json.dumps({"summary": summary}), media_type="application/json")

    except Exception as e:
        return Response(json.dumps({"error": str(e)}), media_type="application/json", status_code=500)


async def context_handler(request: Request) -> Response:
    """Return structured context for chat: prior session summaries + current session messages only."""
    cid = request.query_params.get("campaign_id") or os.environ.get("DEFAULT_CAMPAIGN_ID")
    if not cid:
        return Response(json.dumps({"error": "no campaign_id"}), media_type="application/json")

    try:
        from db import repo as _repo
        async with _repo.tx() as conn:
            # All closed sessions with summaries
            sessions = await _repo.fetchall(
                conn,
                "SELECT id, number, recap, ai_summary FROM sessions "
                "WHERE campaign_id=%s AND ended_at IS NOT NULL ORDER BY number",
                (cid,),
            )

            prior_parts = []
            for s in sessions:
                summ = s.get("ai_summary") or s.get("recap") or ""
                if summ:
                    prior_parts.append(f"Session {s['number']}:\n{summ}")

            prior_summary = "\n\n---\n\n".join(prior_parts) if prior_parts else ""

            # Current (open) session messages only
            open_sess = await _repo.fetchone(
                conn,
                "SELECT id FROM sessions WHERE campaign_id=%s AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
                (cid,),
            )

            if open_sess:
                current_rows = await _repo.fetchall(
                    conn,
                    "SELECT role, speaker, content FROM messages WHERE campaign_id=%s AND session_id=%s ORDER BY created_at",
                    (cid, open_sess["id"]),
                )
            else:
                # No open session — get last 30 messages
                current_rows = await _repo.fetchall(
                    conn,
                    "SELECT role, speaker, content FROM messages WHERE campaign_id=%s ORDER BY created_at DESC LIMIT 30",
                    (cid,),
                )
                current_rows = list(reversed(current_rows))

            current_messages = [
                {"role": r["role"], "content": r["content"], "speaker": r.get("speaker")}
                for r in current_rows
            ]

        return Response(json.dumps({
            "prior_summary": prior_summary,
            "current_messages": current_messages,
            "has_prior": bool(prior_summary),
        }), media_type="application/json")

    except Exception as e:
        return Response(json.dumps({"error": str(e)}), media_type="application/json", status_code=500)


async def ui_handler(request: Request) -> HTMLResponse:
    path = Path(__file__).parent / "ui" / "index.html"
    if not path.exists():
        return HTMLResponse("<h1>UI not found — run from dm-server/</h1>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


# ─── state handler ────────────────────────────────────────────────────────────

async def state_handler(request: Request) -> Response:
    cid = request.query_params.get("campaign_id") or os.environ.get("DEFAULT_CAMPAIGN_ID")
    if not cid:
        return Response(json.dumps({"error": "no campaign_id"}), media_type="application/json")
    try:
        state = await t_state.get_state(campaign_id=cid)
        return Response(json.dumps(state, default=str), media_type="application/json")
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), media_type="application/json", status_code=500)


# ─── chat handler (SSE, Claude + tool loop) ───────────────────────────────────

async def chat_handler(request: Request) -> StreamingResponse:
    try:
        body = await request.json()
    except Exception:
        return Response(json.dumps({"error": "invalid JSON"}), status_code=400, media_type="application/json")

    messages: list = body.get("messages", [])
    campaign_id: str = body.get("campaign_id") or os.environ.get("DEFAULT_CAMPAIGN_ID") or ""
    session_id: str = body.get("session_id") or ""
    speaker: str = body.get("speaker") or ""
    prior_summary: str = body.get("prior_summary") or ""  # compressed prior session context

    tools = _get_tool_schemas()
    ai = anthropic.AsyncAnthropic()

    # ── Build cached system + prior context ───────────────────────────────────
    # System prompt cached (never changes between calls in a session)
    _cached_system = [{"type": "text", "text": _DM_SYSTEM, "cache_control": {"type": "ephemeral"}}]

    # If we have a prior summary, inject it as a stable user/assistant prefix
    # and cache it — it doesn't change within a session
    _base_messages: list = []
    if prior_summary:
        _base_messages = [
            {
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": f"Prior campaign context (read and remember — do not reference these as 'notes', just use them):\n\n{prior_summary}",
                    "cache_control": {"type": "ephemeral"},
                }],
            },
            {
                "role": "assistant",
                "content": "Understood. I have the campaign history and will continue from where we left off.",
            },
        ]

    async def _save_message(role: str, content: str, spk: str | None = None) -> None:
        if not campaign_id:
            return
        try:
            from db import repo as _repo
            async with _repo.tx() as conn:
                await _repo.execute(
                    conn,
                    "INSERT INTO messages (campaign_id, session_id, role, content, speaker) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (campaign_id, session_id or None, role, content, spk or None),
                )
        except Exception:
            pass  # never block chat on message save failure

    async def generate():
        nonlocal messages, session_id
        try:
            # Save the incoming user message (last entry in messages list)
            if messages and messages[-1]["role"] == "user":
                last_user = messages[-1]["content"]
                user_text = last_user if isinstance(last_user, str) else ""
                if user_text and not user_text.startswith("The session is beginning"):
                    await _save_message("user", user_text, speaker or None)

            while True:
                content_blocks = []
                stop_reason = None

                async with ai.messages.stream(
                    model="claude-opus-4-7",
                    max_tokens=8192,
                    system=_cached_system,
                    messages=_base_messages + messages,
                    tools=tools,
                ) as stream:
                    async for event in stream:
                        etype = getattr(event, "type", None)
                        if etype == "content_block_delta":
                            delta = getattr(getattr(event, "delta", None), "text", None)
                            if delta:
                                yield f"data: {json.dumps({'type': 'text', 'delta': delta})}\n\n"
                        elif etype == "content_block_start":
                            cb = getattr(event, "content_block", None)
                            if cb and getattr(cb, "type", None) == "tool_use":
                                yield f"data: {json.dumps({'type': 'tool_start', 'name': cb.name, 'id': cb.id})}\n\n"

                    final = await stream.get_final_message()
                    stop_reason = final.stop_reason
                    content_blocks = final.content

                messages.append({"role": "assistant", "content": [b.model_dump() for b in content_blocks]})

                if stop_reason != "tool_use":
                    # Save final assistant text response
                    assistant_text = "".join(
                        getattr(b, "text", "") for b in content_blocks if hasattr(b, "text")
                    )
                    if assistant_text:
                        await _save_message("assistant", assistant_text)
                        # If start_session returned a session_id, update it for subsequent saves
                    break

                tool_results = []
                state_dirty = False
                for block in content_blocks:
                    if block.type == "tool_use":
                        inputs = dict(block.input or {})
                        if campaign_id:
                            inputs.setdefault("campaign_id", campaign_id)

                        result = await _call_tool(block.name, inputs)
                        result_str = json.dumps(result, default=str)

                        yield f"data: {json.dumps({'type': 'tool_result', 'name': block.name, 'result': result})}\n\n"

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })
                        # Capture session_id when start_session fires
                        if block.name == "start_session" and isinstance(result, dict) and result.get("session_id"):
                            session_id = result["session_id"]
                            yield f"data: {json.dumps({'type': 'session_started', 'session_id': session_id})}\n\n"
                        # Mark state dirty for tools that mutate party/world state
                        if block.name in ("update_character", "update_combatant", "death_save",
                                          "rest", "start_encounter", "end_encounter", "next_turn",
                                          "tick_clock", "upsert_quest", "start_session"):
                            state_dirty = True

                messages.append({"role": "user", "content": tool_results})

                if state_dirty and campaign_id:
                    try:
                        state = await t_state.get_state(campaign_id=campaign_id)
                        yield f"data: {json.dumps({'type': 'state_update', 'state': state}, default=str)}\n\n"
                    except Exception:
                        pass

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"},
    )


# ─── ASGI app ─────────────────────────────────────────────────────────────────

_mcp_inner = mcp.streamable_http_app()

app = Starlette(
    routes=[
        Route("/ui", endpoint=ui_handler),
        Route("/api/campaigns", endpoint=campaigns_handler),
        Route("/api/state", endpoint=state_handler),
        Route("/api/messages", endpoint=messages_handler),
        Route("/api/context", endpoint=context_handler),
        Route("/api/generate-summary", endpoint=generate_summary_handler, methods=["POST"]),
        Route("/api/scene-image", endpoint=scene_image_handler, methods=["POST"]),
        Route("/api/chat", endpoint=chat_handler, methods=["POST", "OPTIONS"]),
        Mount(MOUNT_PATH, app=_mcp_inner),
    ]
)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


if __name__ == "__main__":
    main()
