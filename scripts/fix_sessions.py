"""One-time fix: clean empty session shells + generate summary for session 7.
Run: PYTHONPATH=. python scripts/fix_sessions.py
"""
import asyncio, os
import anthropic
from dotenv import load_dotenv
load_dotenv()
from db import repo

CAMPAIGN_ID = 'e0a6e6bd-9b9e-4a42-af3b-401d6a6dd4ff'

_SUMMARY_PROMPT = """You are summarizing a D&D session for a campaign journal. Write a concise summary (200-300 words) covering:
- Where the session started and ended (locations)
- Key NPCs met, their names and roles
- Major decisions the party made
- Rolls that mattered and outcomes
- Current party status (conditions, resources spent, quests active)
- The most important unresolved thread going into next session

Write in past tense, third person. Include NPC names, location names, and quest names exactly as they appeared."""

async def main():
    async with repo.tx() as conn:
        # 1. Delete empty session shells (sessions with no messages)
        await repo.execute(conn,
            """DELETE FROM sessions WHERE campaign_id=%s AND ended_at IS NOT NULL
               AND id NOT IN (
                   SELECT DISTINCT session_id FROM messages
                   WHERE session_id IS NOT NULL AND campaign_id=%s
               )""",
            (CAMPAIGN_ID, CAMPAIGN_ID))
        print("Deleted empty session shells.")

        # 2. Get the open session (session 7 — has all 51 messages)
        sess = await repo.fetchone(conn,
            "SELECT id, number FROM sessions WHERE campaign_id=%s AND ended_at IS NULL ORDER BY number DESC LIMIT 1",
            (CAMPAIGN_ID,))
        if not sess:
            print("No open session found.")
            return

        session_id = str(sess["id"])
        print(f"Open session: #{sess['number']} ({session_id[:8]}...)")

        # 3. Build transcript from its messages
        msgs = await repo.fetchall(conn,
            "SELECT role, speaker, content FROM messages WHERE campaign_id=%s AND session_id=%s ORDER BY created_at",
            (CAMPAIGN_ID, session_id))
        print(f"  {len(msgs)} messages to summarize.")

        transcript = "\n\n".join(
            f"{'[' + r['speaker'] + ']' if r.get('speaker') else '[DM]'}: {r['content'][:500]}"
            for r in msgs
        )[:15000]

        # 4. Generate summary with Haiku
        print("Generating summary...")
        ai = anthropic.AsyncAnthropic()
        resp = await ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=_SUMMARY_PROMPT,
            messages=[{"role": "user", "content": f"Session transcript:\n\n{transcript}"}],
        )
        summary = resp.content[0].text
        print(f"Summary ({len(summary)} chars) generated.")

        # 5. Close session 7 with summary and a recap
        recap = "Party met Varric Oen at the Gilded Vane. Agreed to infiltrate Cinderquay Warehouse 3 to rescue a child and retrieve a ledger. Posing as Lord Harran Vey of Sellowmarch. Carriage arrives at dusk tomorrow. Varric's full plan revealed."
        await repo.execute(conn,
            "UPDATE sessions SET ended_at=now(), recap=%s, ai_summary=%s WHERE id=%s",
            (recap, summary, session_id))
        print("Session closed with summary.")

        # 6. Show remaining sessions
        sessions = await repo.fetchall(conn,
            "SELECT number, ended_at IS NULL as open, ai_summary IS NOT NULL as has_summary FROM sessions WHERE campaign_id=%s ORDER BY number",
            (CAMPAIGN_ID,))
        print("\nFinal state:")
        for s in sessions:
            print(f"  Session #{s['number']} open={s['open']} has_summary={s['has_summary']}")

    print("\nDone. Restart server and Begin Session — Claude will pick up with full context.")

if __name__ == '__main__':
    asyncio.run(main())
