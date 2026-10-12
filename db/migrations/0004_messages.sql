-- P-UI: persist conversation history per campaign/session.
CREATE TABLE IF NOT EXISTS messages (
    id          uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    session_id  uuid REFERENCES sessions(id) ON DELETE SET NULL,
    role        text NOT NULL CHECK (role IN ('user', 'assistant')),
    content     text NOT NULL,
    speaker     text,   -- 'Jeff', 'Julee', or null for assistant/system
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_campaign_session_idx ON messages(campaign_id, session_id, created_at);
