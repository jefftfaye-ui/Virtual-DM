# dm-server

AI Dungeon Master MCP server. Honest dice, persistent campaign state, SRD rules lookup,
D&D Beyond character import. See `../SPEC.md` for the full design.

## Status

- ✅ Phase 1: dice parser + roller, DB schema, rules modules (damage, death, rest, exhaustion,
  concentration, turn order), MCP server skeleton — 31 tools registered.
- ✅ Phase 2: state tools (get_state, update_character, death_save, rest, set_scene, undo),
  session tools (start/end session, recent events).
- ✅ Phase 3: combat (start_encounter, add_combatant, update_combatant, next_turn, end_encounter).
  Full effect ticking, death_save_due, initiative tiebreaks.
- ✅ Phase 4: world tools — NPCs (knows hidden), locations, secrets (scoped-only), quests,
  clocks (consequence on fill only), lore FTS.
- ✅ Phase 5: SRD ingest (5e-bits/5e-database, CC-BY-4.0), lookup_rule (3-stage), lookup_monster
  (full stat block + structured meta), statblock_ref wired into start_encounter.
- ✅ Phase 6: DDB import — charactercheck 0.7.0 verified on PyPI; derive.py extracts
  abilities/saves/skills/max_hp/slots/hit_dice; HP ratio preserved on re-import;
  overrides always win; AC intentionally not derived (use overrides).
- 🚧 Phase 7: Deploy to Fly.io, claude.ai custom connector.
- 🚧 Phase 7: Deploy to Fly.io, claude.ai custom connector.

## Setup

```bash
cp .env.example .env
# edit .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, CONNECTOR_SECRET (≥32 random bytes URL-safe)
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

Apply DB schema + migrations:

```bash
psql "$SUPABASE_URL" -f db/schema.sql
psql "$SUPABASE_URL" -f db/migrations/0001_current_location.sql
psql "$SUPABASE_URL" -f db/migrations/0002_encounter_turn_init.sql
psql "$SUPABASE_URL" -f db/migrations/0003_srd_meta.sql
```

## SRD ingest

**Source:** `5e-bits/5e-database` — CC-BY-4.0, SRD 5.1 content only.
Repo: https://github.com/5e-bits/5e-database

```bash
# Download + ingest 5.1 from network (requires internet):
python scripts/ingest_srd.py --edition 2014

# From local clone:
python scripts/ingest_srd.py --edition 2014 --from /path/to/5e-database/src

# Wipe and re-ingest (idempotent):
python scripts/ingest_srd.py --edition 2014 --wipe
```

**5.2 (2024 edition):** No structured community conversion confirmed yet. When one exists,
verify it is SRD-only and CC-BY-4.0, then run with `--edition 2024 --from <local dir>`.
Fall back to PDF extraction via `pdfplumber` if needed (see SPEC §6).

## Run tests

```bash
pytest -q
# 107 pass (unit) + N skipped (integration — need SUPABASE_URL)

# With DB:
SUPABASE_URL=postgresql://... pytest -q
```

Test coverage:
- `test_dice.py` — parser, 10k-roll bounds, kh/kl, advantage/disadvantage
- `test_damage.py` — full damage pipeline
- `test_death.py` — death save resolution
- `test_rest.py` — short/long rest by edition
- `test_turn_order.py` — initiative sort, tiebreak, skip logic
- `test_state_logic.py` — slot/resource/hit-die overspend refusal, condition merge
- `test_statblock.py` — normalize_name, extract_monster_meta, format_monster_body
- `test_integration_state.py` — state/session tools (needs DB)
- `test_integration_combat.py` — full §7.3 scripted fight (needs DB)
- `test_integration_world.py` — world tools, secret scoping (needs DB)
- `test_integration_rules.py` — SRD lookup 3 stages, statblock_ref in start_encounter (needs DB)

## Run server (dev)

```bash
python server.py
# serves at http://localhost:8080/mcp/{CONNECTOR_SECRET}
```

## DDB character import

**P6.1 — charactercheck lib:** `charactercheck 0.7.0` exists on PyPI and verified.
Used as primary derivation engine. Falls back to manual derivation on validation failure.

**What is derived:** abilities, proficiency_bonus, saves, skills, max_hp (from DDB's
hitPointInfo), spell_slots, pact_slots (Warlock), hit_dice, level, class_summary, speed.

**What is NOT derived:** `ac` — too many edge cases (magic items, Unarmored Defense, etc.).
Set via `update_character(overrides={"ac": N})` after import.

```bash
# From a laptop (datacenter IPs often blocked):
python scripts/import_ddb.py https://www.dndbeyond.com/characters/12345 Jeff

# Dry run to see what would be derived:
python scripts/import_ddb.py 12345 Jeff --dry-run

# Re-import after level-up (preserves HP ratio and overrides):
python scripts/import_ddb.py 12345 Jeff

# Full reset (fresh HP, conditions, slots):
python scripts/import_ddb.py 12345 Jeff --reset-live-state
```

Mismatches between derived and existing values are printed, not hidden.
Fix with: `update_character(overrides={"field": value})`

## Seed a campaign

```bash
python scripts/seed_campaign.py --name "Stormwreck Isle" --edition 2014
# Prints DEFAULT_CAMPAIGN_ID → add to .env
# Then import characters + ingest SRD as instructed
```

## Deploy

Target Fly.io (avoids serverless cold-start timeouts on long tool calls).

### First deploy

```bash
fly launch            # creates app, detects Dockerfile
fly secrets set \
  SUPABASE_URL="postgresql://..." \
  SUPABASE_SERVICE_KEY="..." \
  CONNECTOR_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  DEFAULT_CAMPAIGN_ID="<uuid from seed_campaign.py>" \
  RULES_EDITION="2014"
fly deploy
```

### Verify schema budget before deploy

```bash
PYTHONPATH=. python scripts/measure_schema.py
# Must print "✓ Within budget." — target ≤ 6k tokens
# Current: ~5,363 tokens (31 tools)
```

### Connect to claude.ai

1. Open claude.ai → Settings → Custom Connectors
2. Add connector URL: `https://<fly-app>.fly.dev/mcp/<CONNECTOR_SECRET>`
3. Enable the connector in your DM Project
4. Apply **all** SPEC §8 Project instruction changes:
   - Speaker labels (`Jeff:` / `Julee:` prefix required)
   - Missing-server fallback ("say so out of character if tools unavailable")
   - `death_save` tool for death saves (not `roll`)
   - Concentration follow-up when `concentration_check` returned
   - Secret rolls via `roll(visibility="secret", dc=…)`
   - `get_npc(dm_view=true)` only when NPC shares information
   - Lines and veils filled in (stored in `dm_only` lore, not instructions)

### Secret rotation runbook

**Run quarterly or on suspected exposure:**

```bash
NEW_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
fly secrets set CONNECTOR_SECRET="$NEW_SECRET"
fly deploy
# Then update the connector URL in claude.ai Settings → Custom Connectors
```

### Log redaction

Fly.io logs the full request path including the connector secret. Options:
- Use Fly's log shipping to a private drain with server-side redaction
- Or accept the risk and rotate the secret if logs are ever exposed

### Backup

Supabase provides automatic daily backups. For manual snapshot:

```bash
pg_dump "$SUPABASE_URL" --no-owner -F c -f backup_$(date +%Y%m%d).dump
```

### Subsequent deploys

```bash
fly deploy    # rebuilds image, zero-downtime swap
```

## Schema migrations

Run in order after applying `db/schema.sql`:

| File | What it adds |
|------|--------------|
| `0001_current_location.sql` | `campaigns.current_location_id` for set_scene |
| `0002_encounter_turn_init.sql` | `encounters.turn_index` default −1 |
| `0003_srd_meta.sql` | `srd_chunks.meta jsonb` for structured monster stats |

## Attribution

Content from the D&D 5.1 System Reference Document, Wizards of the Coast, CC-BY-4.0.
Source: https://github.com/5e-bits/5e-database (CC-BY-4.0, SRD-only).
