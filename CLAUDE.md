# dm-server — Claude Code context

AI Dungeon Master MCP server. See SPEC.md (parent dir) for full design.

## Architecture

- **Server:** FastMCP (`mcp<2`), streamable HTTP, stateless. Path-gated by `CONNECTOR_SECRET`.
- **DB:** Supabase Postgres. Pool via `psycopg3`. All mutations wrap `repo.tx()`.
- **Auth:** Unguessable URL path (`/mcp/{CONNECTOR_SECRET}`). Upgrade path: OAuth 2.1.
- **31 tools total** — budget tracked in `scripts/measure_schema.py` (~5,363 tokens).

## Key invariants

1. **Dice only via `tools.dice._roll_impl`** — never call `secrets.SystemRandom` elsewhere.
2. **Every mutating tool:** check idempotency → mutate → write event → store idempotency.
3. **Events append-only.** Never UPDATE or DELETE from `events` or `rolls`.
4. **`prev` in event payload** — every mutating event stores pre-image so `undo_last_event` works.
5. **Secrets scoped-only.** No tool exposes all campaign secrets. `get_secrets` requires type+id.
6. **AC never derived** from DDB — always set via `update_character(overrides={"ac": N})`.
7. **turn_index = -1** on fresh encounter (no one has gone yet). First `next_turn` → index 0.

## Tool `_impl` pattern

Every tool has:
- **`_impl(conn, ...)`** — accepts caller connection, used by integration tests + tool-to-tool calls
- **`public_fn(...)`** — opens `repo.tx()`, calls `_impl`, returns result

Tests call `_impl` directly on their rolled-back connection.

## Test split

- **Unit tests** (no DB): `test_dice`, `test_damage`, `test_death`, `test_rest`, `test_turn_order`, `test_state_logic`, `test_statblock`, `test_derive`
- **Integration tests** (need `SUPABASE_URL`): `test_integration_*` — skip cleanly without DB

```bash
pytest -q                          # 128 pass, 84 skip
SUPABASE_URL=postgresql://... pytest -q   # all 212 run
```

## File layout

```
server.py                 FastMCP app, path auth, 31 tool registrations
tools/
  _util.py                shared: resolve_campaign_id, write_event, to_str
  dice.py                 roll + record_player_roll; _roll_impl for within-tx use
  state.py                get_state, update_character, death_save, rest, set_scene, undo
  sessions.py             start/end session, get_recent_events
  combat.py               start/add/update_combatant, next_turn, end_encounter
  world.py                NPCs, locations, secrets (scoped), quests, clocks, lore
  rules.py                lookup_rule, lookup_monster; _lookup_monster_meta for combat
  ddb_tool.py             import_ddb_character (MCP wrapper)
rules/
  damage.py               resist/immune/vuln pipeline, temp HP, massive damage
  death.py                death save resolution
  rest.py                 short/long rest recovery by edition
  exhaustion.py           2014 table + 2024 d20 penalty
  concentration.py        state verbs
  turn_order.py           sort, tiebreak, skip, next_index
  statblock.py            normalize_name, extract_monster_meta, format_*_body
dice/parser.py            strict notation grammar, SystemRandom, adv/dis, kh/kl
ddb/
  client.py               ONLY file that knows DDB URL/shape — fail loudly
  derive.py               charactercheck primary + manual fallback
  importer.py             upsert logic: overrides win, HP ratio, event log
db/
  schema.sql              full schema + triggers
  migrations/             0001–0003 incremental
  repo.py                 pool, tx(), fetchone/fetchall/execute, idempotency helpers
scripts/
  ingest_srd.py           5e-bits/5e-database download + chunk insert
  import_ddb.py           local DDB fetch + derive + upsert (primary path)
  seed_campaign.py        create campaign + starter lore
  measure_schema.py       token budget check (run before deploy)
```

## Adding a new tool

1. Implement `_impl(conn, ...)` + public wrapper in appropriate `tools/*.py`
2. Register in `server.py` with `mcp.tool()(fn)` or `@mcp.tool()`
3. Update tool count comment in `server.py`
4. Run `scripts/measure_schema.py` — must stay ≤ 6k tokens
5. Add integration test calling `_impl` directly

## Common gotchas

- `mcp` pinned to `<2` — v2 renamed FastMCP to MCPServer
- `turn_index` starts at -1 (migration 0002) — not 0
- `srd_chunks.meta` added in migration 0003 — run all migrations in order
- `update_combatant` for PCs proxies to `_update_character_impl` then mirrors HP back
- `start_encounter` pulls settings (edition, massive_damage) fresh per monster entry — cached query
- DDB endpoint returns `{"data": {...}}` — `client.fetch_character()` returns the inner dict
- charactercheck requires the inner `data` dict, not the wrapper

## Deploy checklist

```
[ ] psql schema.sql + all migrations applied
[ ] SRD ingested: python scripts/ingest_srd.py --edition 2014
[ ] Campaign seeded: python scripts/seed_campaign.py
[ ] Characters imported: python scripts/import_ddb.py ...
[ ] AC set via overrides on both characters
[ ] PYTHONPATH=. python scripts/measure_schema.py → ✓ Within budget
[ ] fly secrets set (SUPABASE_URL, CONNECTOR_SECRET, DEFAULT_CAMPAIGN_ID)
[ ] fly deploy
[ ] Connector added in claude.ai + SPEC §8 instructions applied
[ ] 10-minute test scene with one combat + one death save
```
