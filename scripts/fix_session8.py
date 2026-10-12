"""Delete bogus session 8 and its messages."""
import asyncio
from dotenv import load_dotenv
load_dotenv()
from db import repo

CAMPAIGN_ID = 'e0a6e6bd-9b9e-4a42-af3b-401d6a6dd4ff'

async def main():
    async with repo.tx() as conn:
        await repo.execute(conn,
            "DELETE FROM messages WHERE campaign_id=%s AND session_id=(SELECT id FROM sessions WHERE campaign_id=%s AND number=8)",
            (CAMPAIGN_ID, CAMPAIGN_ID))
        await repo.execute(conn,
            "DELETE FROM sessions WHERE campaign_id=%s AND number=8",
            (CAMPAIGN_ID,))
        print("Session 8 deleted.")

asyncio.run(main())
