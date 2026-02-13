-- Team-level meal scan schema (PostgreSQL)
-- Run via psql/alembic migration in production.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'meal_type_enum') THEN
        CREATE TYPE meal_type_enum AS ENUM ('breakfast', 'lunch', 'dinner');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS meal_scans (
    id BIGSERIAL PRIMARY KEY,
    hackathon_id BIGINT NOT NULL REFERENCES hackathons(id) ON DELETE CASCADE,
    participant_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id BIGINT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    meal_type meal_type_enum NOT NULL,
    scanned_by BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_meal_scan_once_per_meal UNIQUE (hackathon_id, participant_id, meal_type)
);

CREATE INDEX IF NOT EXISTS ix_meal_scans_team_id ON meal_scans(team_id);
CREATE INDEX IF NOT EXISTS ix_meal_scans_meal_type ON meal_scans(meal_type);
CREATE INDEX IF NOT EXISTS ix_meal_scans_hackathon_team_meal ON meal_scans(hackathon_id, team_id, meal_type);
CREATE INDEX IF NOT EXISTS ix_team_members_team_id ON team_members(team_id);
