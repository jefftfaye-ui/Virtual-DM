-- P2.6: set_scene needs to link a location to the current scene.
ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS current_location_id uuid REFERENCES locations(id) ON DELETE SET NULL;
