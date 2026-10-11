-- P3: use -1 as initial turn_index (no one has gone yet).
-- next_turn advances from -1 → 0 on the first call.
ALTER TABLE encounters ALTER COLUMN turn_index SET DEFAULT -1;
