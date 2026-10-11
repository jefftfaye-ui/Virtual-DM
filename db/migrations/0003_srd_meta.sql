-- P5: structured monster metadata alongside readable body text.
-- meta stores {ac, hp, hit_dice, dex_mod, resistances, immunities, vulnerabilities}
-- so start_encounter can use statblock_ref without parsing text.
ALTER TABLE srd_chunks ADD COLUMN IF NOT EXISTS meta jsonb;
