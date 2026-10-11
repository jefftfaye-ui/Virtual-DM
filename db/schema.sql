-- AI DM MCP server — Supabase Postgres schema (SPEC §2).
-- Extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── campaigns ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS campaigns (
    id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            text NOT NULL,
    edition         text NOT NULL CHECK (edition IN ('2014','2024')),
    setting_summary text,
    current_scene   text,
    in_game_date    text,
    active                boolean NOT NULL DEFAULT true,
    settings              jsonb NOT NULL DEFAULT '{"monster_hp_mode":"average","massive_damage":true}'::jsonb,
    current_location_id   uuid,  -- set via set_scene; FK added after locations table
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

-- ─── characters (PCs) ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS characters (
    id                uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id       uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    player_name       text NOT NULL,
    name              text NOT NULL,
    ddb_id            text,
    ddb_snapshot      jsonb,
    ddb_synced_at     timestamptz,
    level             int NOT NULL DEFAULT 1,
    class_summary     text,
    ac                int,
    max_hp            int NOT NULL,
    hp                int NOT NULL,
    temp_hp           int NOT NULL DEFAULT 0,
    speed             int,
    abilities         jsonb NOT NULL DEFAULT '{"str":10,"dex":10,"con":10,"int":10,"wis":10,"cha":10}'::jsonb,
    saves             jsonb NOT NULL DEFAULT '{}'::jsonb,
    skills            jsonb NOT NULL DEFAULT '{}'::jsonb,
    overrides         jsonb NOT NULL DEFAULT '{}'::jsonb,
    resistances       text[] NOT NULL DEFAULT '{}',
    immunities        text[] NOT NULL DEFAULT '{}',
    vulnerabilities   text[] NOT NULL DEFAULT '{}',
    conditions        text[] NOT NULL DEFAULT '{}',
    exhaustion        int NOT NULL DEFAULT 0,
    inspiration       boolean NOT NULL DEFAULT false,
    death_saves       jsonb NOT NULL DEFAULT '{"successes":0,"failures":0}'::jsonb,
    stable            boolean NOT NULL DEFAULT false,
    dead              boolean NOT NULL DEFAULT false,
    concentrating_on  text,
    hit_dice          jsonb NOT NULL DEFAULT '{}'::jsonb,
    spell_slots       jsonb NOT NULL DEFAULT '{}'::jsonb,
    pact_slots        jsonb,
    resources         jsonb NOT NULL DEFAULT '{}'::jsonb,
    inventory         jsonb NOT NULL DEFAULT '[]'::jsonb,
    gold              int NOT NULL DEFAULT 0,
    notes             text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS characters_campaign_idx ON characters(campaign_id);

-- ─── NPCs / locations / secrets / quests / clocks / lore ─────────────
CREATE TABLE IF NOT EXISTS locations (
    id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id   uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    name          text NOT NULL,
    region        text,
    description   text,
    notes         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS locations_campaign_idx ON locations(campaign_id);

-- FK deferred until after locations exists
ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_current_location_id_fkey;
ALTER TABLE campaigns
    ADD CONSTRAINT campaigns_current_location_id_fkey
    FOREIGN KEY (current_location_id) REFERENCES locations(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS npcs (
    id                 uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id        uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    name               text NOT NULL,
    role               text,
    location_id        uuid REFERENCES locations(id) ON DELETE SET NULL,
    disposition        int NOT NULL DEFAULT 0 CHECK (disposition BETWEEN -3 AND 3),
    wants              text,
    fears              text,
    knows              text,
    public_description text,
    status             text NOT NULL DEFAULT 'alive' CHECK (status IN ('alive','dead','missing')),
    notes              text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS npcs_campaign_idx ON npcs(campaign_id);

CREATE TABLE IF NOT EXISTS secrets (
    id             uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id    uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    text           text NOT NULL,
    tied_to_type   text NOT NULL CHECK (tied_to_type IN ('npc','location','quest','none')),
    tied_to_id     uuid,
    revealed       boolean NOT NULL DEFAULT false,
    revealed_at    timestamptz,
    revealed_how   text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS secrets_scope_idx ON secrets(campaign_id, tied_to_type, tied_to_id);

CREATE TABLE IF NOT EXISTS quests (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id  uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    title        text NOT NULL,
    status       text NOT NULL DEFAULT 'rumor' CHECK (status IN ('rumor','active','done','failed')),
    summary      text,
    giver_npc_id uuid REFERENCES npcs(id) ON DELETE SET NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS quests_campaign_idx ON quests(campaign_id);

CREATE TABLE IF NOT EXISTS clocks (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id  uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    name         text NOT NULL,
    segments     int NOT NULL CHECK (segments > 0),
    filled       int NOT NULL DEFAULT 0,
    consequence  text,
    visible      boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS clocks_campaign_idx ON clocks(campaign_id);

CREATE TABLE IF NOT EXISTS lore (
    id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    title       text NOT NULL,
    body        text NOT NULL,
    tags        text[] NOT NULL DEFAULT '{}',
    dm_only     boolean NOT NULL DEFAULT false,
    tsv         tsvector GENERATED ALWAYS AS (
                    to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,''))
                ) STORED,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lore_campaign_idx ON lore(campaign_id);
CREATE INDEX IF NOT EXISTS lore_tsv_idx       ON lore USING gin(tsv);

-- ─── combat ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS encounters (
    id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    name        text NOT NULL,
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active','ended')),
    round       int NOT NULL DEFAULT 1,
    turn_index  int NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS encounters_campaign_idx ON encounters(campaign_id);

CREATE TABLE IF NOT EXISTS combatants (
    id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    encounter_id    uuid NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
    kind            text NOT NULL CHECK (kind IN ('pc','monster','npc')),
    ref_id          uuid,
    name            text NOT NULL,
    initiative      int,
    dex_mod         int NOT NULL DEFAULT 0,
    tiebreak        int,
    ac              int NOT NULL,
    max_hp          int NOT NULL,
    hp              int NOT NULL,
    temp_hp         int NOT NULL DEFAULT 0,
    resistances     text[] NOT NULL DEFAULT '{}',
    immunities      text[] NOT NULL DEFAULT '{}',
    vulnerabilities text[] NOT NULL DEFAULT '{}',
    conditions      text[] NOT NULL DEFAULT '{}',
    concentrating_on text,
    status          text NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','down','dead','fled','removed')),
    statblock_ref   text,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS combatants_encounter_idx ON combatants(encounter_id);

CREATE TABLE IF NOT EXISTS effects (
    id                   uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    encounter_id         uuid NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
    target_combatant_id  uuid NOT NULL REFERENCES combatants(id) ON DELETE CASCADE,
    source_combatant_id  uuid REFERENCES combatants(id) ON DELETE SET NULL,
    anchor_combatant_id  uuid REFERENCES combatants(id) ON DELETE SET NULL,
    name                 text NOT NULL,
    ends                 text NOT NULL CHECK (ends IN ('start_of_turn','end_of_turn')),
    rounds_left          int NOT NULL,
    concentration        boolean NOT NULL DEFAULT false,
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS effects_encounter_idx ON effects(encounter_id);

-- ─── append-only log ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id           uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id  uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    number       int NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    recap        text
);
CREATE UNIQUE INDEX IF NOT EXISTS sessions_campaign_number_idx ON sessions(campaign_id, number);

CREATE TABLE IF NOT EXISTS rolls (
    id              uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id     uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    session_id      uuid REFERENCES sessions(id) ON DELETE SET NULL,
    encounter_id    uuid REFERENCES encounters(id) ON DELETE SET NULL,
    actor           text NOT NULL,
    reason          text NOT NULL,
    expression      text NOT NULL,
    mode            text NOT NULL CHECK (mode IN ('normal','advantage','disadvantage')),
    source          text NOT NULL CHECK (source IN ('server','player')),
    natural_roll    int,
    dice            jsonb NOT NULL,
    modifier        int NOT NULL DEFAULT 0,
    total           int NOT NULL,
    visibility      text NOT NULL CHECK (visibility IN ('public','secret')),
    dc              int,
    outcome         text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rolls_campaign_time_idx  ON rolls(campaign_id, created_at);
CREATE INDEX IF NOT EXISTS rolls_encounter_idx      ON rolls(encounter_id);

CREATE TABLE IF NOT EXISTS events (
    id                    uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id           uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    session_id            uuid REFERENCES sessions(id) ON DELETE SET NULL,
    type                  text NOT NULL,
    payload               jsonb NOT NULL,
    reason                text,
    out_of_session        boolean NOT NULL DEFAULT false,
    compensates_event_id  uuid REFERENCES events(id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_campaign_time_idx ON events(campaign_id, created_at);

-- ─── idempotency store (SPEC §4.7, gap added in review) ──────────────
CREATE TABLE IF NOT EXISTS request_ids (
    campaign_id uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    request_id  text NOT NULL,
    result      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (campaign_id, request_id)
);
CREATE INDEX IF NOT EXISTS request_ids_time_idx ON request_ids(created_at);
-- TODO cron: delete request_ids older than 7 days

-- ─── SRD index ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS srd_chunks (
    id         uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    edition    text NOT NULL CHECK (edition IN ('2014','2024')),
    kind       text NOT NULL CHECK (kind IN ('rule','spell','monster','item','condition')),
    name       text NOT NULL,
    name_norm  text NOT NULL,
    body       text NOT NULL,
    meta       jsonb,   -- structured data for monsters: {ac, hp, hit_dice, dex_mod, resistances, ...}
    tsv        tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED
);
CREATE INDEX IF NOT EXISTS srd_chunks_tsv_idx       ON srd_chunks USING gin(tsv);
CREATE INDEX IF NOT EXISTS srd_chunks_name_trgm_idx ON srd_chunks USING gin(name_norm gin_trgm_ops);
CREATE INDEX IF NOT EXISTS srd_chunks_edition_kind_idx ON srd_chunks(edition, kind);

-- ─── updated_at trigger ───────────────────────────────────────────────
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DO $$ DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'campaigns','characters','npcs','locations','secrets','quests',
    'clocks','lore','encounters','combatants'
  ] LOOP
    EXECUTE format(
      'DROP TRIGGER IF EXISTS trg_touch_%I ON %I;
       CREATE TRIGGER trg_touch_%I BEFORE UPDATE ON %I
         FOR EACH ROW EXECUTE FUNCTION touch_updated_at();',
      t, t, t, t
    );
  END LOOP;
END $$;
