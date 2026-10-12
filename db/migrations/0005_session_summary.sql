-- P-cost: store AI-generated session summaries for context compression.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ai_summary text;
