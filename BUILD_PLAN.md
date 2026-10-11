# dm-server — Build Plan

Executor-ready plan for Phases 2–7. Phase 1 shipped (see README "Status").
Every task references SPEC.md section + Phase-1 modules it builds on.
Each task has: **Deliverable**, **Files**, **Dependencies**, **Acceptance**.

---

## Working rules (apply to every phase)

1. **Pure logic in `rules/`, I/O in `tools/`.** Don't put DB calls in `rules/*`.
2. **Every mutating tool wraps in `repo.tx()`** — one transaction per tool call,
   state row + `events` row in the same tx.
3. **Every mutating tool checks `check_idempotent` first, calls `store_idempotent` last.**
4. **Compact JSON responses.** Default <2 KB; `get_state` <4 KB. Serialize UUIDs as strings.
5. **Explicit errors.** Return `{"error": "...", "hint": "..."}` on bad input. Never fail silently.
6. **Dice always via `tools/dice.roll`.** Nothing else may call `secrets.SystemRandom`.
7. **No new tools without updating `tools/__init__.py` export list, `server.py` registration,
   and the Tool-count comment in `server.py`.** Budget is 31.
8. **Tests before merging a phase.** Phase acceptance = `pytest -q` green + the phase scenario
   from SPEC §7 runs end-to-end.
9. **Commit cadence:** one commit per task below. Message: `<phase>.<task>: <terse what>`.
   Example: `p2.3: update_character damage path integration`.
10. **Caveman mode OK for commit titles, normal English for commit bodies.**

---

## Shared setup before Phase 2

Must exist locally:

- `.env` with `SUPABASE_URL` pointing at a dev Postgres (Supabase local or a dedicated project).
- `psql "$SUPABASE_URL" -f db/schema.sql` run clean.
- One campaigns row seeded for tests; put its UUID in `DEFAULT_CAMPAIGN_ID`.

Add a tiny fixture helper for integration tests:

**File:** `tests/conftest.py`
- `db` fixture: ensures schema, starts a tx, yields a conn, rolls back on teardown.
- `campaign_id` fixture: creates (or reuses) a test campaign.
- `character_id` fixture: inserts a basic PC with sane defaults.

---

# Phase 2 — State + Sessions (SPEC §3 "State", "Sessions")

Goal: a DM can start a session, snapshot state, mutate a PC, run death saves, rest,
set a scene, and undo the last mutation.

## P2.1 — session machinery

**Deliverable:** `tools/sessions.py` fully wired.

**Files:**
- `tools/sessions.py` — replace stubs:
  - `start_session(campaign_id?)`:
    - Insert `sessions` with `number = max(existing)+1`.
    - Return `{"session_id": ..., "number": ..., "state": await get_state(...), "recent_recaps": [...]}` (last 2 recaps).
  - `end_session(recap, campaign_id?)`: set `ended_at = now()`, store recap, return `{"session_id", "number"}`.
  - `get_recent_events(n=20, campaign_id?)`: return last `n` events (id, type, created_at, reason). Not payloads unless small.

**Dependencies:** `db/repo.py`, `tools/state.get_state` (next task).

**Acceptance:**
- Integration test starts a session, ends it with a recap, re-starts a new session,
  confirms `start_session` returns the two most recent recaps.

## P2.2 — get_state

**Deliverable:** `tools/state.get_state` returning a <4 KB snapshot.

**Files:**
- `tools/state.py` — implement `get_state(include=["party","scene","encounter","quests","clocks"], campaign_id?)`.
  - `party`: id, name, player_name, class_summary, level, ac, hp, max_hp, temp_hp,
    conditions, concentrating_on, death_saves (counts only), stable, dead,
    spell_slots (max/used), pact_slots, hit_dice (max/used), inspiration, exhaustion.
  - `scene`: campaigns.current_scene + in_game_date + location name if `set_scene` stored one.
  - `encounter`: current active encounter (id, name, round, turn_index, combatants [name, kind,
    hp/max_hp, status, initiative]). No stat blocks, no resistances dump.
  - `quests`: title, status, summary.
  - `clocks`: id, name, filled, segments, visible. **For `visible=false`, omit `consequence`.**
- **Must omit:** `secrets.*`, `lore` with `dm_only=true`, `npcs.knows`, hidden clock
  consequences.

**Acceptance:**
- Unit test: insert secrets + dm_only lore + hidden clock, call `get_state`, assert none appear.
- Snapshot test: payload <4 KB with 4 PCs, 1 encounter (6 combatants), 3 quests, 2 clocks.

## P2.3 — update_character core (damage + heal paths)

**Deliverable:** `update_character` applying damage/heal via `rules/damage.py`.

**Files:**
- `tools/state.py` — implement `update_character(character_id, reason, request_id?=None, ...)`:
  - Load character row FOR UPDATE.
  - Build `TargetState` from row.
  - Branches (apply in order if multiple provided):
    1. `damage` → `rules.damage.apply_damage(target, DamageInput(**damage), edition, massive_damage_enabled)`.
       Write back hp/temp_hp/concentrating_on (clear if `ended_concentration`), bump death_failures
       capped at 3; set `dead` if outcome says so.
    2. `heal` → `rules.damage.apply_heal`.
    3. `set_hp`, `temp_hp`: direct writes with clamp.
    4. `add_conditions`, `remove_conditions`: text[] union/diff, dedupe lowercased.
    5. `use_slot(level)`: refuse with `{"error": "...", "hint": "..."}` if `used >= max`. Same for `restore_slot`.
    6. `use_pact_slot` / `restore_pact_slot`: same, on `pact_slots`.
    7. `use_resource(name)` / `restore_resource(name)`: same, on `resources`.
    8. `spend_hit_dice(die_key, count=1)`: refuse if `used + count > max`.
    9. `start_concentration(label)` / `end_concentration()`.
    10. `inspiration (bool)`, `inventory_add`, `inventory_remove`, `gold_delta`,
        `exhaustion_delta` (floor 0, no ceiling here — exhaustion.describe handles that).
    11. `overrides (dict merge)`.
  - Write one `events` row with full payload (what changed) + `reason`.
  - Return the response from the damage/heal path PLUS `{"hp_after": ..., "temp_hp_after": ...,
    "conditions": [...]}` plus any `concentration_check` dict.
  - If exhaustion changed, include `{"exhaustion": {level, effect: describe(...)}}`.

**Acceptance:**
- All SPEC §7.2 unit cases pass via tool-level integration tests:
  resist order, temp HP first, massive damage, death-save failure increment, concentration DC,
  overspend refused, hit-die refused.

## P2.4 — death_save

**Deliverable:** `tools/state.death_save`.

**Files:**
- `tools/state.py` — `death_save(character_id, request_id?)`:
  - Refuse if `hp > 0` or `stable` or `dead` with explicit error.
  - Call `tools.dice.roll("1d20", reason="death save", actor=character.name,
    campaign_id=..., visibility="public")` → use `natural`.
  - `rules.death.resolve(natural, successes, failures)`.
  - Apply: set `death_saves`, `stable`, `dead`; if `regained_hp` set `hp=1`.
  - Event log entry.
  - Response: `{"roll_id", "natural", "successes", "failures", "stable", "dead", "message"}`.

**Acceptance:** nat20 → `hp=1`; three failures → `dead`; three successes → `stable`;
error when already dead/stable/up.

## P2.5 — rest

**Deliverable:** `tools/state.rest`.

**Files:**
- `tools/state.py` — `rest(kind, character_ids=[], reason, request_id?)`:
  - For each PC: load, apply `rules.rest.short_rest` or `rules.rest.long_rest(edition=campaign.edition)`.
  - Hit-die healing is NOT done here. Caller handles separately with `roll` + `update_character(heal=...)`.
  - One `events` row per character with the diff.
- Response: `{"applied": [{"character_id": ..., "diff": {...}}]}`.

**Acceptance:** Fixture PC with slots used + exhaustion 2 → long rest → full slots, exhaustion 1,
hit-dice recovered per edition.

## P2.6 — set_scene

**Deliverable:** `tools/state.set_scene`.

**Files:**
- Updates `campaigns.current_scene`, optional `in_game_date`, optional link to a location via
  a new `campaigns.current_location_id` column:
  - **Schema change:** add migration `db/migrations/0001_current_location.sql`:
    `ALTER TABLE campaigns ADD COLUMN current_location_id uuid REFERENCES locations(id) ON DELETE SET NULL;`
  - Update `get_state` scene block to include the location name if set.
- Writes `events` row.

**Acceptance:** set_scene → get_state reflects new scene + date + location name.

## P2.7 — undo_last_event

**Deliverable:** `tools/state.undo_last_event`.

**Files:**
- `tools/state.py` — `undo_last_event(reason, campaign_id?)`:
  - Find most-recent event in current session where `compensates_event_id IS NULL` and type ≠ `roll`.
  - Switch on event type → revert affected state row with the pre-image stored in payload.
    Payload must contain `prev` dict for this to work.
  - Append a new event `{type: "undo", compensates_event_id: ..., payload: {reverted_type, ...}}`
    in the same transaction.
  - Stop at session start: refuse if the newest undoable event precedes the active session's
    `started_at`.
  - **Never undoes `rolls`.**

**Dependency change:** every mutating tool from P2.3+ must include a `prev` snapshot of changed
fields in the event payload so undo can replay in reverse.

**Acceptance:**
- Damage → undo → HP restored.
- Rest → undo → slots/HP restored.
- Repeated undo walks backward through N events.
- Undo across session boundary refuses.
- Roll events are skipped.

## P2.8 — hook state tools into server.py

Already wired as stubs in `server.py`. Replace the `mcp.tool()(t_state.*)` decorators with
`@mcp.tool()` wrappers that type the arguments properly for schema generation. Confirm total
tool count still = 31.

**Acceptance:** `python server.py` starts; MCP client lists all 31 tools; schema token size
is measured and reported (SPEC §3 target ≤ 6k). Add `scripts/measure_schema.py` that imports
the server and prints the serialized tool list length.

---

# Phase 3 — Combat (SPEC §3 "Combat")

Goal: a full scripted fight runs end-to-end per SPEC §7.3.

## P3.1 — start_encounter

**Files:**
- `tools/combat.py` — `start_encounter(name, monsters, reason, request_id?)`:
  - Insert `encounters` row.
  - For each `monsters` entry: expand `count`, auto-name "Goblin 1/2/3".
  - If `statblock_ref` matches an SRD row (via `rules.lookup` → defer to Phase 5; for now
    accept required `ac` + `hp` if ref unmatched), use its AC/HP/resistances/immunities/vulnerabilities.
  - HP:
    - `campaigns.settings.monster_hp_mode == "average"` → use stat block average (defer to Phase 5
      — Phase 3 can hard-require explicit `hp`).
    - `"rolled"` → roll the stat block's hit-dice expression via `tools.dice.roll` and use it.
  - Roll monster initiative with `tools.dice.roll("1d20+<dex_mod>", reason="initiative", ...)`.
  - PCs: insert combatants with `initiative = NULL`; DM sets via `update_combatant(initiative=…)`.
- Response: `{encounter_id, combatants: [{id, name, initiative, hp/max_hp}]}`.

**Acceptance:** Start fight with 3 goblins + 2 PCs. Auto-naming correct; monster initiatives
rolled; PCs have null initiative.

## P3.2 — add_combatant

**Files:**
- `tools/combat.py` — `add_combatant(encounter_id, kind, name, reason, request_id?, ...)`:
  - Monsters without initiative: roll via dice tool.
  - Validate `encounters.status == 'active'`.
- Writes event.

**Acceptance:** Mid-fight add goblin; it rolls initiative; appears in sort order.

## P3.3 — update_combatant

**Files:**
- `tools/combat.py` — `update_combatant(combatant_id, reason, request_id?, ...)`:
  - If `combatants.kind == 'pc'`: find `characters` row via `ref_id`, call `update_character` with
    the same damage/heal/conditions/concentration args. Mirror HP back to combatants row so
    `next_turn` sees up-to-date HP.
  - Monsters/NPCs: apply the damage pipeline directly on the combatant row (reuse `rules.damage`).
    - Monster dropped to 0: `status='dead'` unless `nonlethal=true` AND damage was melee →
      `status='down'`.
  - `status='fled'|'removed'`: just sets status.
  - `add_effect / remove_effect`: insert/delete `effects` row; `concentration=true` effects
    tracked for auto-end.
- Writes event.

**Acceptance:**
- PC damage via combatant round-trips to characters.hp.
- Monster drops to 0 → dead by default; nonlethal → down.
- Concentration ends mid-fight → all `effects` with that `source_combatant_id` + `concentration=true`
  are removed and listed in response.

## P3.4 — next_turn

**Files:**
- `tools/combat.py` — `next_turn(encounter_id?, campaign_id?)`:
  - Load encounter + combatants; build `rules.turn_order.CombatantView` list.
  - `assign_tiebreaks`; if any new tiebreaks assigned, UPDATE back + event entry.
  - `sort_initiative` → compute ordered list.
  - Advance index via `next_index(ordered, encounters.turn_index)`.
  - If `rounds_advanced > 0`, bump `encounters.round`.
  - Tick effects: load `effects` for this encounter; decrement `rounds_left` for effects whose
    anchor combatant just crossed the correct boundary (`start_of_turn` → anchor's start, etc.).
    Collect expired, delete them.
  - Build response: `{round, current: {combatant_id, name, kind, hp_status}, expired_effects,
    death_save_due}`. `death_save_due=true` iff current is a PC with hp=0 and not stable/dead.
- Writes event.

**Acceptance:** SPEC §7.3 scripted fight passes:
1. 2 PCs vs 3 SRD goblins.
2. Round-2 reinforcement added.
3. One goblin flees mid-fight.
4. Initiative tie → broken by dex then tiebreak.
5. A PC drops → next_turn returns `death_save_due`.
6. 1-round effect expires on correct boundary.

## P3.5 — end_encounter

**Files:**
- `tools/combat.py` — `end_encounter(encounter_id, reason, outcome_summary)`:
  - `UPDATE encounters SET status='ended'`.
  - `DELETE FROM effects WHERE encounter_id = ...` (encounter-scoped effects clear).
  - Clear `concentrating_on` on any PC whose concentration was an effect from this encounter.
  - Event row with `outcome_summary` in payload.

**Acceptance:** After end, `get_state(include=["encounter"])` returns no active encounter.

---

# Phase 4 — World, Secrets, Clocks, Lore (SPEC §3 "World")

Goal: Julee can add/edit NPCs, locations, quests, clocks, lore; secrets stay scoped.

## P4.1 — upsert_npc / get_npc

**Files:**
- `tools/world.py`:
  - `upsert_npc(id?, name, role?, location_id?, disposition?, wants?, fears?, knows?,
    public_description?, status?, notes?, reason, request_id?)`: INSERT ... ON CONFLICT (id)
    DO UPDATE. Writes event.
  - `get_npc(name_or_id, dm_view=false, campaign_id?)`:
    - Resolve name_or_id (name match: case-insensitive, trim; fail if ambiguous).
    - Default fields: id, name, role, location name, disposition, wants, fears,
      public_description, status.
    - `dm_view=true` adds `knows`.
    - **Never returns linked secrets** — those come from `get_secrets`.

**Acceptance:**
- Default call omits `knows`.
- `dm_view=true` includes `knows`.
- Fetching an NPC never includes anything from `secrets`.

## P4.2 — upsert_location / get_location

**Files:** mirror P4.1 for `locations`.

**Acceptance:** CRUD round-trip.

## P4.3 — secrets

**Files:**
- `tools/world.py`:
  - `add_secret(text, tied_to_type, tied_to_id, reason, request_id?)`: INSERT. Event.
  - `get_secrets(tied_to_type, tied_to_id, campaign_id?)`: SELECT scoped. **No "list all" tool.**
  - `reveal_secret(secret_id, how, request_id?)`: `revealed=true, revealed_at, revealed_how`. Event.

**Acceptance:** no tool path returns all secrets at once; `get_secrets` requires both scope args.

## P4.4 — quests + clocks

**Files:**
- `tools/world.py`:
  - `upsert_quest(id?, title, status, summary?, giver_npc_id?, reason)`: upsert.
  - `upsert_clock(id?, name, segments, filled?, consequence?, visible?, reason)`: upsert.
  - `tick_clock(clock_id, segments=1, reason, request_id?)`:
    - UPDATE `filled = min(segments, filled + segments)`.
    - If `filled == segments`: return `{"filled": true, "consequence": clock.consequence}`.
    - Otherwise return `{"filled": false, "progress": "X/Y"}`.
    - For hidden clocks, consequence is only returned when filled; `get_state` already omits it.
    - Event entry with pre/post.

**Acceptance:**
- Tick to fill → consequence returned.
- Tick a hidden clock partway → `get_state` shows filled/segments but no consequence.

## P4.5 — lore

**Files:**
- `tools/world.py`:
  - `upsert_lore(id?, title, body, tags, dm_only, reason, request_id?)`: upsert.
  - `get_lore(query, campaign_id?)`:
    - `SELECT ... FROM lore WHERE campaign_id = $1 AND tsv @@ websearch_to_tsquery('english', $2)
       ORDER BY ts_rank(tsv, ...) LIMIT 5`.
    - Return each with `dm_only` flag so the DM knows not to narrate it directly.

**Acceptance:** fulltext finds lore by partial match; dm_only rows are returned but flagged.

---

# Phase 5 — SRD ingest + lookups (SPEC §3 "Rules", §6)

Goal: `lookup_rule` and `lookup_monster` return clean, chunked SRD content.

## P5.1 — pick + verify source

**Deliverable:** written decision in `README.md` with source URL + license line.

- Prefer `5e-bits/5e-database` for 5.1 (verify SRD-only, CC-BY-4.0, 5.2 coverage status).
- If 5.2 not covered: ingest 5.2 from the official SRD PDF via a Python PDF-to-text pass
  (`pdfplumber` or `pymupdf`) with hand-tuned heading splits. Document the fallback.

**Acceptance:** License + source documented. Both editions have SOME content path chosen.

## P5.2 — ingest script

**Files:**
- `scripts/ingest_srd.py`:
  - For each item (spell/monster/condition/rule/item):
    - `name_norm = re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()`.
    - `body` is the chunk's full text (one logical section per row).
    - Insert into `srd_chunks (edition, kind, name, name_norm, body)`.
  - Idempotent: delete all `WHERE edition=$1` then re-insert (SRD is small).
  - CLI: `python scripts/ingest_srd.py --edition 2014 --from <path-or-url>`.

**Acceptance:** `SELECT count(*) FROM srd_chunks WHERE edition='2014'` ≥ several hundred.
Chunks for "grappled", "fireball", "goblin" all exist.

## P5.3 — lookup_rule

**Files:**
- `tools/rules.py` — `lookup_rule(query, kind=None)`:
  - Normalize query to `name_norm` form.
  - Stage 1: exact `name_norm = $1`.
  - Stage 2: `similarity(name_norm, $1) > 0.4` (pg_trgm). ORDER BY similarity DESC. LIMIT 3.
  - Stage 3: `tsv @@ websearch_to_tsquery('english', $1)`. ORDER BY ts_rank. LIMIT 3.
  - Return top 3 with `{name, kind, matched_stage, body: body[:1500]}`.

**Acceptance:**
- `lookup_rule("grappled")` returns Grappled condition at stage 1.
- `lookup_rule("grapple")` returns something sensible at stage 2.
- `lookup_rule("stops you moving")` returns Grappled or Restrained at stage 3.

## P5.4 — lookup_monster

**Files:**
- `tools/rules.py` — `lookup_monster(name)`: same three stages but constrained to `kind='monster'`.
  Returns full body (not truncated).
- `tools/combat.start_encounter` can now call `lookup_monster` internally to pull AC/HP when
  `statblock_ref` matches; `monster_hp_mode="average"` uses the parsed average HP.
  - **New helper:** `rules/statblock.py` with `parse_hp_expression("8d6+8") -> ("8d6+8", 36)`
    where 36 is the stated average. Store the chunk's name + body; parsing is best-effort.

**Acceptance:** `lookup_monster("goblin")` returns the full goblin stat block. Fuzzy misspellings
("gob", "goblins") still return goblin as top hit via stage 2.

---

# Phase 6 — D&D Beyond import (SPEC §3 "DDB")

Goal: both characters import via local script; derived values listed vs sheet;
unresolved fields set via `overrides`.

## P6.1 — verify charactercheck lib

**Files:** `README.md` — add a note: verified exists / unverified → fall back to hand-derivation.
`pip install charactercheck` or equivalent; if nothing works, hand-derive only the simple fields.

**Acceptance:** README states the actual decision.

## P6.2 — derive.py

**Files:**
- `ddb/derive.py` — `derive(snapshot) -> dict`:
  - abilities (base scores → mods).
  - proficiency_bonus from level.
  - saves (ability + proficiency flag).
  - skills (prof + expertise).
  - max_hp (level + Con mod + hit-die base; add "Tough" if the feat is present).
  - spell_slots table from class levels.
  - pact_slots if Warlock present.
  - hit_dice from class levels.
  - level, class_summary ("Wiz 5 / Rog 1").
  - speed from race.
  - Do NOT compute AC. Leave null → `overrides.ac` from the player.

**Acceptance:** For two fixture snapshots, derived values match the DDB sheet within explicit
list of exceptions. Mismatches printed, not hidden.

## P6.3 — import_ddb.py (local)

**Files:**
- `scripts/import_ddb.py`:
  - `fetch_character(id)` via `ddb.client`.
  - `derive(data)`.
  - Load existing character by `(campaign_id, ddb_id)` if present.
  - Merge: `overrides` always win; `inventory` user-edits preserved; `hp` preserves ratio when
    `reset_live_state=false` (compute `old_ratio = hp / max_hp`, apply to new `max_hp`,
    round down, floor 1 unless the PC was dead).
  - Upsert into `characters`. Event row with `type: "ddb_import"`, payload includes derived
    vs overrides diff.

**Acceptance:** Running the script twice is idempotent. Re-import after level-up preserves
`overrides` and HP ratio.

## P6.4 — import_ddb_character tool

**Files:**
- `tools/ddb_tool.py` — wraps `scripts/import_ddb.py`. On fetch failure, return
  `{"error": "DDB fetch blocked", "hint": "run scripts/import_ddb.py from a laptop"}`.

**Acceptance:** Tool failure returns the specific hint. Tool success produces same output as
the local script.

---

# Phase 7 — Deploy + connect (SPEC §7.7)

## P7.1 — Dockerfile + fly.toml

**Files:**
- `Dockerfile`:
  ```
  FROM python:3.12-slim
  WORKDIR /app
  COPY pyproject.toml .
  RUN pip install -e .
  COPY . .
  CMD ["python", "server.py"]
  ```
- `fly.toml`: single process, internal port 8080, HTTPS forced, `[env]` with non-secret vars,
  secrets set via `fly secrets set`.

**Acceptance:** `fly launch` + `fly deploy` yields a reachable HTTPS endpoint.

## P7.2 — schema token measurement

**Files:**
- `scripts/measure_schema.py`:
  - Import server, extract the registered tool JSON schemas, serialize, print byte + rough
    token count (`len(json) / 4` as a proxy).
- Run before deploy. If > 6k tokens, trim tool arg descriptions.

**Acceptance:** Script prints the number. Documented in README.

## P7.3 — custom connector in claude.ai

- Add `https://<host>/mcp/<CONNECTOR_SECRET>` as a custom connector.
- Enable in the DM Project.
- Apply SPEC §8 instruction changes (checklist in Project instructions):
  - Speaker labels, missing-server fallback, death_save usage, concentration follow-up,
    secret-roll usage, dm_view usage, lines/veils filled in.

**Acceptance:** 10-minute test scene including one combat and one death save runs cleanly.

## P7.4 — ops notes

**Files:**
- `README.md` additions:
  - Secret rotation runbook: generate new secret → `fly secrets set CONNECTOR_SECRET=...`
    → `fly deploy` → update connector URL in claude.ai.
  - Log redaction (Fly: `log_redaction = ["CONNECTOR_SECRET"]` or drain filter).
  - Backup: Supabase scheduled dumps.

**Acceptance:** Runbooks written. Secret rotated once end-to-end to verify.

---

# Later (SPEC §7.8 — explicit non-goals until MVP ships)

- Push-to-talk voice page (STT → Claude API → TTS).
- DDB game-log reader.
- Player-facing web view of party + quests.
- OAuth 2.1 (upgrade from path-secret when anyone besides Jeff + Julee uses it).

---

## Milestones

| Phase | What done means | Rough size |
|-------|-----------------|-----------|
| 2 | 10 state/session tools green; integration test covers damage + death save + rest + undo | 1 session |
| 3 | §7.3 scripted fight passes end-to-end | 1 session |
| 4 | 12 world tools green; secrets never leak via get_state | 0.5 session |
| 5 | SRD content ingested; three fuzzy lookups match | 1 session (depends on source quality) |
| 6 | Both characters import; mismatch list produced | 0.5 session + manual tuning |
| 7 | Deployed, connected, 10-minute scene played | 0.5 session |

Target: MVP playable in ~4 focused sessions after Phase 1.

---

## Executor checklist (every task)

- [ ] Read the SPEC section referenced.
- [ ] Write the test first where the task has `rules/` logic (TDD). Integration tests after.
- [ ] Implement.
- [ ] `pytest -q` green.
- [ ] Commit: `p<X>.<Y>: <terse>` subject, body explains anything non-obvious.
- [ ] Update this file's status column if the shape of the task changed.

## When unsure

- Prefer `tools/` returning explicit `{"error", "hint"}` over throwing.
- Prefer compact JSON over verbose.
- Prefer refusing an action with a reason over silently coercing.
- When a rule has 2014 vs 2024 divergence, read it from `campaigns.edition`, not from env.
- When a tool needs state another tool owns (e.g. combat touching characters), use the owner's
  tool internally; don't duplicate logic.
