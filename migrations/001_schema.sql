-- CalLens database schema
-- RLS is enabled on every data table from the start so it can never be retrofitted incorrectly.

-- ────────────────────────────────────────────────────────────────────────────
-- Extensions
-- ────────────────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for full-text search on transcripts later

-- ────────────────────────────────────────────────────────────────────────────
-- App roles
-- ────────────────────────────────────────────────────────────────────────────
-- calllens      : superuser / migration owner (used only in docker-compose / CI)
-- calllens_app  : the FastAPI / worker processes — limited to DML, no DDL
-- calllens_rls  : connection role used at query time; session vars drive RLS

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'calllens_app') THEN
    CREATE ROLE calllens_app LOGIN PASSWORD 'calllens_app_dev';
  END IF;
END $$;

-- ────────────────────────────────────────────────────────────────────────────
-- Tenants
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        TEXT UNIQUE NOT NULL,           -- e.g. "aegiscloud"
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE
);

-- Seed the demo tenant so ingestion can reference it
INSERT INTO tenants (id, slug, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'aegiscloud', 'Aegis Cloud')
ON CONFLICT (slug) DO NOTHING;

-- ────────────────────────────────────────────────────────────────────────────
-- Accounts (customer companies that appear in calls)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS accounts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    domain      TEXT,                           -- e.g. "summittrust.com"
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);

ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;

CREATE POLICY accounts_tenant_isolation ON accounts
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON accounts TO calllens_app;

-- ────────────────────────────────────────────────────────────────────────────
-- Calls
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS calls (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    meeting_id      TEXT NOT NULL,              -- original meetingId from meeting-info.json
    title           TEXT NOT NULL,
    organizer_email TEXT NOT NULL,
    host_email      TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    ended_at        TIMESTAMPTZ NOT NULL,
    duration_mins   NUMERIC(6,2) NOT NULL,
    raw_folder      TEXT NOT NULL,              -- path to source folder (for reprocessing)
    content_hash    TEXT NOT NULL,              -- SHA-256 of all 6 source files; idempotency key
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, meeting_id)
);

ALTER TABLE calls ENABLE ROW LEVEL SECURITY;

CREATE POLICY calls_tenant_isolation ON calls
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON calls TO calllens_app;
CREATE INDEX IF NOT EXISTS calls_tenant_started ON calls (tenant_id, started_at DESC);

-- ────────────────────────────────────────────────────────────────────────────
-- Participants (one row per person per call)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS participants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    call_id     UUID NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    name        TEXT,
    is_internal BOOLEAN NOT NULL DEFAULT FALSE  -- @aegiscloud.com = internal
);

ALTER TABLE participants ENABLE ROW LEVEL SECURITY;

CREATE POLICY participants_tenant_isolation ON participants
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT ON participants TO calllens_app;
CREATE INDEX IF NOT EXISTS participants_call ON participants (call_id);
CREATE INDEX IF NOT EXISTS participants_email_tenant ON participants (tenant_id, email);

-- ────────────────────────────────────────────────────────────────────────────
-- Transcript turns
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transcript_turns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    call_id         UUID NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    turn_index      INTEGER NOT NULL,
    speaker_name    TEXT NOT NULL,
    speaker_id      INTEGER,
    sentence        TEXT NOT NULL,
    sentiment_type  TEXT,                       -- neutral / positive / negative
    start_time_secs NUMERIC(10,3),
    end_time_secs   NUMERIC(10,3),
    confidence      NUMERIC(4,3)
);

ALTER TABLE transcript_turns ENABLE ROW LEVEL SECURITY;

CREATE POLICY transcript_turns_tenant_isolation ON transcript_turns
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT ON transcript_turns TO calllens_app;
CREATE INDEX IF NOT EXISTS turns_call ON transcript_turns (call_id, turn_index);

-- ────────────────────────────────────────────────────────────────────────────
-- Call summaries (from the pre-existing summary.json)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS call_summaries (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    call_id             UUID NOT NULL UNIQUE REFERENCES calls(id) ON DELETE CASCADE,
    summary_text        TEXT NOT NULL,
    overall_sentiment   TEXT,                   -- very-positive / mixed-positive / mixed-negative / etc.
    sentiment_score     NUMERIC(3,1),           -- 1.0–5.0
    topics              TEXT[] NOT NULL DEFAULT '{}',
    action_items        TEXT[] NOT NULL DEFAULT '{}',
    key_moments         JSONB NOT NULL DEFAULT '[]'
);

ALTER TABLE call_summaries ENABLE ROW LEVEL SECURITY;

CREATE POLICY call_summaries_tenant_isolation ON call_summaries
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON call_summaries TO calllens_app;

-- ────────────────────────────────────────────────────────────────────────────
-- Call classifications (written by the classifier agent — Phase 2)
-- Defined now so the schema is complete; rows arrive in Phase 2.
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS call_classifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    call_id         UUID NOT NULL UNIQUE REFERENCES calls(id) ON DELETE CASCADE,
    call_type       TEXT NOT NULL CHECK (call_type IN ('support','external','internal')),
    account_id      UUID REFERENCES accounts(id),
    confidence      NUMERIC(4,3) NOT NULL,
    needs_review    BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by     TEXT,                       -- email of human reviewer if HITL triggered
    reviewed_at     TIMESTAMPTZ,
    classified_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE call_classifications ENABLE ROW LEVEL SECURITY;

CREATE POLICY classifications_tenant_isolation ON call_classifications
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON call_classifications TO calllens_app;

-- ────────────────────────────────────────────────────────────────────────────
-- Persona insights (written by insight writer agents — Phase 2)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TYPE persona_role AS ENUM ('support_lead','sales_manager','product_manager','eng_lead');

CREATE TABLE IF NOT EXISTS insights (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    account_id      UUID REFERENCES accounts(id),
    persona         persona_role NOT NULL,
    insight_type    TEXT NOT NULL,              -- churn_risk / recurring_issue / feature_gap / escalation_pattern
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    severity        TEXT CHECK (severity IN ('low','medium','high','critical')),
    evidence_call_ids UUID[] NOT NULL DEFAULT '{}',
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    batch_id        TEXT NOT NULL               -- which pipeline run produced this
);

ALTER TABLE insights ENABLE ROW LEVEL SECURITY;

CREATE POLICY insights_tenant_isolation ON insights
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE ON insights TO calllens_app;
CREATE INDEX IF NOT EXISTS insights_tenant_persona ON insights (tenant_id, persona);
CREATE INDEX IF NOT EXISTS insights_account ON insights (account_id);

-- ────────────────────────────────────────────────────────────────────────────
-- LangGraph pipeline checkpoints (Phase 2 — table must exist for import)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline_checkpoints (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    batch_id    TEXT NOT NULL,
    thread_id   TEXT NOT NULL,
    checkpoint  JSONB NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, batch_id, thread_id)
);

GRANT SELECT, INSERT, UPDATE ON pipeline_checkpoints TO calllens_app;

-- ────────────────────────────────────────────────────────────────────────────
-- User memory (Phase 4 — defined now so schema is complete)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_sub    TEXT NOT NULL,                  -- JWT sub claim
    role        persona_role NOT NULL,
    content     TEXT NOT NULL,                  -- compacted conversation summary
    entities    JSONB NOT NULL DEFAULT '{}',    -- {accounts:[], topics:[]} mentioned
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ                     -- NULL = keep forever
);

ALTER TABLE user_memories ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_memories_tenant_isolation ON user_memories
    USING (tenant_id = current_setting('app.tenant_id', TRUE)::UUID);

GRANT SELECT, INSERT, UPDATE, DELETE ON user_memories TO calllens_app;
CREATE INDEX IF NOT EXISTS memories_user ON user_memories (tenant_id, user_sub, created_at DESC);
