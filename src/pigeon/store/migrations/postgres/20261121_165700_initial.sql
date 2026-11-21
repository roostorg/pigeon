-- Initial Pigeon PostgreSQL schema (orgs, api_tokens, policies,
-- modelspec_versions, org_model_bindings).
-- Idempotent so databases initialized before versioned migrations adopt this
-- baseline cleanly without data loss.

CREATE TABLE IF NOT EXISTS orgs (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id),
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at DOUBLE PRECISION NOT NULL,
    revoked_at DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS policies (
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    base TEXT NOT NULL,
    base_version TEXT,
    policy_text TEXT NOT NULL,
    display TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (org_id, name, version)
);

CREATE TABLE IF NOT EXISTS modelspec_versions (
    org_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (org_id, name, version)
);

CREATE TABLE IF NOT EXISTS org_model_bindings (
    org_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    spec_version TEXT NOT NULL,
    endpoint TEXT,
    credential_ref TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (org_id, model_name)
);

-- Pre-migration databases may have a policies table without base_version.
-- Check the catalog first so we do not take an AccessExclusiveLock when the
-- column already exists.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'policies'
          AND column_name = 'base_version'
    ) THEN
        SET LOCAL lock_timeout = '5s';
        ALTER TABLE policies ADD COLUMN base_version TEXT;
    END IF;
END $$;
