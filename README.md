# Virtual DM

An AI Dungeon Master for two players. Claude narrates and runs the story. The server enforces rules — honest dice, tracked HP, spell slots, conditions, combat, death saves — so the DM never has to remember them.

Supports voice narration, AI-generated scene art and tactical maps, session history, and D&D Beyond character import.

---

## What you need

| Requirement | Notes |
|---|---|
| Python 3.11 or newer | Check with `python3 --version`. [Download](https://www.python.org/downloads/) if you're older. |
| [Anthropic API key](https://console.anthropic.com) | Powers the DM. ~$3–5 per 2-hour session on Opus. |
| [Supabase account](https://supabase.com) | Free tier. Stores campaign state, sessions, messages. |
| [OpenAI API key](https://platform.openai.com/api-keys) | Optional. Powers voice (onyx) + scene/map images. ~$1–2 per session. |

Prebuilt binaries aren't published yet, so everyone runs from source. It's five commands.

---

## Step 1 — Install

```bash
git clone https://github.com/jefftfaye-ui/Virtual-DM.git
cd Virtual-DM
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

If `pip install` says the package "requires a different Python", your `python3` is older than 3.11. Install a newer one and create the venv with it, e.g. `python3.12 -m venv .venv`.

---

## Step 2 — Set up Supabase (the database)

1. Create a free account at [supabase.com](https://supabase.com) and click **New project**. Any region. **Write down the database password you choose** — you need it below.
2. Create the tables. Open **SQL Editor** in the left sidebar, then for each file below paste its contents and click **Run**. Do them in this order:
   - `db/schema.sql`
   - `db/migrations/0001_current_location.sql`
   - `db/migrations/0002_encounter_turn_init.sql`
   - `db/migrations/0003_srd_meta.sql`
   - `db/migrations/0004_messages.sql`
   - `db/migrations/0005_session_summary.sql`

   If you have `psql` installed you can do the same from the terminal:
   ```bash
   export DB="postgresql://...your connection string from step 3..."
   for f in db/schema.sql db/migrations/*.sql; do psql "$DB" -f "$f"; done
   ```
3. Get your **Database URL**. Click **Connect** at the top of the Supabase dashboard, choose **Session pooler**, copy the URI, and replace `[YOUR-PASSWORD]` with the password from step 1. It looks like:
   ```
   postgresql://postgres.abcdefghijkl:PASSWORD@aws-0-us-east-1.pooler.supabase.com:5432/postgres
   ```
   (The "Direct connection" string also works, but only on networks with IPv6. Session pooler works everywhere.)

---

## Step 3 — Launch and fill in the setup screen

```bash
python launcher.py
```

Your browser opens `http://localhost:8080/setup`. Fill in:

| Field | Required | Where to get it | What it's for |
|---|---|---|---|
| Anthropic API Key | Yes | [console.anthropic.com](https://console.anthropic.com) → API Keys | The DM's brain. |
| OpenAI API Key | No | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | DM voice and scene/map art. Blank = system text-to-speech, no art. |
| Database URL | Yes | Step 2, part 3 | Where all game state lives. |
| Service Role Key | No | Supabase → Settings → API Keys → `service_role` | Not used yet. Leave blank. |
| Default Campaign ID | No | Printed by Step 4 | Skips the campaign picker. Blank = pick each time. |
| Player 1 / 2 name | No | — | Labels on the two chat boxes. Defaults: Jeff and Julee. |

Click **Save & Start Playing**. Settings are saved to `~/.virtualdm/config.json` on your machine (readable only by you) and never sent anywhere. The server also generates a random *connector secret* for you; it only matters if you later hook the server up to claude.ai as an MCP connector, so there's nothing to do.

**Mac:** from now on you can skip the terminal — double-click `VirtualDM.app` in the repo folder. It starts the server (or opens the game if it's already running).

**Prefer a `.env` file?** Copy `.env.example` to `.env` in the repo folder and fill it in. It holds the same settings under their environment-variable names (`ANTHROPIC_API_KEY`, `SUPABASE_URL`, …). If both exist, `~/.virtualdm/config.json` wins.

---

## Step 4 — Create your first campaign

In the same terminal (venv active, inside the repo folder):

```bash
PYTHONPATH=. python scripts/seed_campaign.py --name "Your Campaign Name" --edition 2014
```

The script reads your Database URL from the setup screen's config (or `.env`), creates the campaign with starter lore, and prints its ID. The campaign shows up in the picker right away. Optionally paste the ID into the setup screen as Default Campaign ID to skip the picker.

---

## Import characters from D&D Beyond

Characters must be set to **Public** on D&D Beyond.

```bash
# Run from your own computer (cloud IPs are often blocked by D&D Beyond). Reads the DB URL from your setup config.
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

1. Start the server: `python launcher.py` (Mac: double-click `VirtualDM.app`)
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
