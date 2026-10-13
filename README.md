# Virtual DM

An AI Dungeon Master for two players. Claude narrates and runs the story. The server enforces rules — honest dice, tracked HP, spell slots, conditions, combat, death saves — so the DM never has to remember them.

Supports voice narration, AI-generated scene art and tactical maps, session history, and D&D Beyond character import.

---

## What you need

| Requirement | Notes |
|---|---|
| [Anthropic API key](https://console.anthropic.com) | Powers the DM. ~$3–5 per 2-hour session on Opus. |
| [OpenAI API key](https://platform.openai.com/api-keys) | Optional. Powers voice (onyx) + scene/map images. ~$1–2 per session. |
| [Supabase account](https://supabase.com) | Free tier. Stores campaign state, sessions, messages. |
| Python 3.12+ | For running from source. Not needed for the binary. |

---

## Option A — Download the binary (easiest)

Download the latest release for your platform from the [Releases](../../releases) page:

- `VirtualDM-mac` — macOS (Apple Silicon + Intel)
- `VirtualDM-linux` — Linux x86_64
- `VirtualDM-win.exe` — Windows 10/11

**Mac/Linux:** make it executable first:
```bash
chmod +x VirtualDM-mac
./VirtualDM-mac
```

**Windows:** double-click `VirtualDM-win.exe`.

A browser window opens automatically at the setup screen.

---

## Option B — Run from source

```bash
git clone https://github.com/jefftfaye-ui/Virtual-DM.git
cd Virtual-DM/dm-server
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
python launcher.py
```

---

## First-time setup

The setup screen (`http://localhost:8080/setup`) opens automatically on first run.

Fill in:

1. **Anthropic API Key** — from [console.anthropic.com](https://console.anthropic.com)
2. **OpenAI API Key** — optional, from [platform.openai.com](https://platform.openai.com/api-keys)
3. **Supabase Database URL** — `postgresql://postgres:PASSWORD@db.YOURREF.supabase.co:5432/postgres`
4. **Supabase Service Role Key** — from your Supabase project → Settings → API
5. **Player names** — defaults to Jeff and Julee. Change to whatever you want.

Settings are saved to `~/.virtualdm/config.json` on your machine. Never transmitted anywhere.

### Setting up Supabase

1. Create a free account at [supabase.com](https://supabase.com)
2. Create a new project (any region, any password)
3. Go to Settings → Database → Connection string, copy the URI
4. Go to Settings → API, copy the `service_role` key
5. Apply the database schema (one-time setup, see below)

---

## Database schema setup

This is a one-time step. You need `psql` installed ([download](https://www.postgresql.org/download/)).

```bash
cd dm-server    # or wherever you cloned the repo

export DB="postgresql://postgres:PASSWORD@db.YOURREF.supabase.co:5432/postgres"

psql "$DB" -f db/schema.sql
psql "$DB" -f db/migrations/0001_current_location.sql
psql "$DB" -f db/migrations/0002_encounter_turn_init.sql
psql "$DB" -f db/migrations/0003_srd_meta.sql
psql "$DB" -f db/migrations/0004_messages.sql
psql "$DB" -f db/migrations/0005_session_summary.sql
```

---

## Create your first campaign

```bash
# From the dm-server directory with venv active:
PYTHONPATH=. python scripts/seed_campaign.py --name "Your Campaign Name" --edition 2014

# Copy the printed DEFAULT_CAMPAIGN_ID into the setup screen
```

This creates the campaign and seeds starter lore. Update the Campaign ID in the setup screen, then restart.

---

## Import characters from D&D Beyond

Characters must be set to **Public** on D&D Beyond.

```bash
# Run from a laptop (cloud IPs are often blocked by D&D Beyond):
PYTHONPATH=. python scripts/import_ddb.py https://www.dndbeyond.com/characters/ID Player1Name \
  --campaign-id YOUR_CAMPAIGN_ID

PYTHONPATH=. python scripts/import_ddb.py https://www.dndbeyond.com/characters/ID Player2Name \
  --campaign-id YOUR_CAMPAIGN_ID
```

After import, set AC manually — it can't be derived reliably from D&D Beyond:

Tell the DM in the game: `"Set [CharacterName]'s AC to 16"` — it will call the right tool.

**What's imported automatically:** ability scores, saving throws, skills, max HP, spell slots, pact slots (Warlock), hit dice, level, speed.

**Re-import after leveling up:** run the same command again. HP ratio is preserved; your edits survive.

---

## Ingest the SRD (optional but recommended)

Gives the DM access to monster stat blocks, spell descriptions, and rules lookups.

```bash
PYTHONPATH=. python scripts/ingest_srd.py --edition 2014
```

Downloads ~900 entries from the D&D 5.1 System Reference Document (CC-BY-4.0).

---

## Playing

1. Start the server: `python launcher.py` (or run the binary)
2. Open `http://localhost:8080/ui` in your browser
3. Select your campaign
4. Click **Begin Session**

The DM opens the scene. Jeff types in the left input, Julee in the right. Send with Enter or the arrow button. Hold the mic button to speak.

### Voice narration

Click the **🔇** button in the top bar to enable DM voice. With an OpenAI key configured, the DM uses the `onyx` voice (deep, cinematic). Without it, falls back to your system's text-to-speech.

### Scene art

When the DM sets a new location, a scene image appears automatically in the center panel (requires OpenAI key).

### Maps

Type a description in the map box and click **Map it** to generate a top-down tactical map. The DM can also trigger this automatically when handing the party a map.

### Ending a session

Tell the DM: `"End the session"` — it will save a recap and generate a summary for next time. Next session picks up from where you left off.

---

## Customization

### Change player names

Open `http://localhost:8080/setup` and update the player name fields. Restart.

### Change campaigns

The campaign picker shows all active campaigns. To add a new one:

```bash
PYTHONPATH=. python scripts/seed_campaign.py --name "New Campaign" --edition 2014
```

### Monster HP mode

Edit the campaign settings in Supabase (`campaigns.settings`):
- `"monster_hp_mode": "average"` — monsters use the listed average HP (default)
- `"monster_hp_mode": "rolled"` — monsters roll their hit dice on spawn

### Rules edition

Set `RULES_EDITION=2024` in the setup screen or config file for D&D 2024 rules (hit dice recovery, exhaustion, concentration DCs differ).

### Tone and world

The DM's behavior is guided by its system prompt in `server.py`. You can edit `_DM_SYSTEM` to change its style, add setting-specific rules, or adjust narration tone.

Lines and veils (content you want off-limits or off-screen) live in the campaign's `dm_only` lore entries. Add them with:

```
Tell the DM: "Add a dm-only lore entry: [your lines and veils]"
```

---

## Building binaries yourself

```bash
pip install pyinstaller
python build.py
# Output: dist/VirtualDM
```

To build for all platforms automatically, push a git tag (e.g. `v1.0.0`) to GitHub. The Actions workflow produces Mac, Linux, and Windows binaries as downloadable artifacts.

---

## Costs

| Service | What for | Rough cost |
|---|---|---|
| Anthropic | DM (claude-opus-4-7) | ~$3–5 per 2hr session |
| OpenAI TTS | DM voice (onyx) | ~$0.30 per session |
| OpenAI Images | Scene art + maps | ~$0.50–1.00 per session |
| Supabase | Database | Free tier (no cost) |

Sessions get cheaper over time as prior sessions are summarized and cached.

---

## Attribution

Includes content from the D&D 5.1 System Reference Document, Wizards of the Coast, CC-BY-4.0.
SRD source: [5e-bits/5e-database](https://github.com/5e-bits/5e-database) (CC-BY-4.0, SRD-only content).
