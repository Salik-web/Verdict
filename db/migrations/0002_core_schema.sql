-- 0002_core_schema.sql — the core multi-tenant schema.
--
-- This SQL is the SINGLE SOURCE OF TRUTH for the data model. The Drizzle schema
-- (apps/api) and SQLAlchemy models (services/pipeline) MIRROR it by hand.
--
-- Conventions (see db/SCHEMA.md for the full contract):
--   * UUID primary keys via gen_random_uuid(), EXCEPT high-volume append-ish
--     tables (mentions, audit_logs, llm_cost_log) which use bigint identity
--     for index locality.
--   * Every business table carries account_id (the tenant key) and is indexed
--     on it. accounts is the tenant root and has no account_id.
--   * created_at/updated_at on every table, EXCEPT the immutable log tables
--     (audit_logs, llm_cost_log) which are append-only and carry created_at only.
--   * Lifecycle state machines use Postgres ENUMs (DB-enforced). Open taxonomies
--     that live in config (engine names, gap_type, categories, asset/fact types)
--     are free TEXT — never hardcoded as enums.

-- ---------------------------------------------------------------------------
-- Shared updated_at trigger
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- Enums (lifecycle state machines)
-- ---------------------------------------------------------------------------
CREATE TYPE user_role AS ENUM ('owner', 'admin', 'member');
CREATE TYPE scan_status AS ENUM ('pending', 'running', 'completed', 'failed', 'canceled');
CREATE TYPE job_status AS ENUM ('queued', 'running', 'succeeded', 'failed', 'canceled');
CREATE TYPE gap_status AS ENUM ('open', 'planned', 'in_progress', 'resolved', 'dismissed');
CREATE TYPE asset_status AS ENUM ('draft', 'generated', 'validated', 'published', 'rejected');
CREATE TYPE asset_validation_state AS ENUM ('pending', 'passed', 'failed');
CREATE TYPE verification_verdict AS ENUM ('improved', 'no_change', 'regressed', 'inconclusive');

-- ---------------------------------------------------------------------------
-- accounts — the tenant root
-- ---------------------------------------------------------------------------
CREATE TABLE accounts (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name                   text NOT NULL,
  slug                   text NOT NULL,
  domain                 text,
  -- Own brand tracked for share-of-voice (own vs competitors).
  brand_name             text,
  brand_aliases          text[] NOT NULL DEFAULT '{}',
  -- Plan / subscription (billing wired in a later phase).
  plan                   text NOT NULL DEFAULT 'free',
  subscription_status    text NOT NULL DEFAULT 'trialing',
  trial_ends_at          timestamptz,
  current_period_end     timestamptz,
  stripe_customer_id     text,
  stripe_subscription_id text,
  settings               jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX accounts_slug_key ON accounts (slug);
CREATE TRIGGER trg_accounts_updated_at BEFORE UPDATE ON accounts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- users — belong to an account
-- ---------------------------------------------------------------------------
CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id    uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  email         text NOT NULL,
  name          text,
  role          user_role NOT NULL DEFAULT 'member',
  password_hash text,
  status        text NOT NULL DEFAULT 'active',
  last_login_at timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
-- Email is globally unique (a person maps to one account for now); revisit if
-- we need the same email across accounts.
CREATE UNIQUE INDEX users_email_lower_key ON users (lower(email));
CREATE INDEX users_account_id_idx ON users (account_id);
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- competitors — tracked brands per account (is_self marks the account's own)
-- ---------------------------------------------------------------------------
CREATE TABLE competitors (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  name       text NOT NULL,
  domain     text,
  aliases    text[] NOT NULL DEFAULT '{}',
  is_self    boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX competitors_account_name_key ON competitors (account_id, lower(name));
CREATE INDEX competitors_account_id_idx ON competitors (account_id);
CREATE TRIGGER trg_competitors_updated_at BEFORE UPDATE ON competitors
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- prompts — tracked questions per account
-- ---------------------------------------------------------------------------
CREATE TABLE prompts (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id   uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  text         text NOT NULL,
  category     text,
  prompt_group text,
  active       boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX prompts_account_id_idx ON prompts (account_id);
CREATE INDEX prompts_account_active_idx ON prompts (account_id, active);
CREATE TRIGGER trg_prompts_updated_at BEFORE UPDATE ON prompts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- scans — one measurement run across an engine set
-- ---------------------------------------------------------------------------
CREATE TABLE scans (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id   uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  status       scan_status NOT NULL DEFAULT 'pending',
  engine_set   jsonb NOT NULL DEFAULT '[]'::jsonb,
  triggered_by text,
  started_at   timestamptz,
  finished_at  timestamptz,
  stats        jsonb NOT NULL DEFAULT '{}'::jsonb,
  error        text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX scans_account_id_idx ON scans (account_id);
CREATE INDEX scans_account_created_idx ON scans (account_id, created_at DESC);
CREATE INDEX scans_account_status_idx ON scans (account_id, status);
CREATE TRIGGER trg_scans_updated_at BEFORE UPDATE ON scans
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- mentions — TIME-SERIES, the largest table. One row per
-- (scan, prompt, engine, run). bigint identity PK for volume; raw responses
-- are stored externally and referenced, never inlined.
-- ---------------------------------------------------------------------------
CREATE TABLE mentions (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id       uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  scan_id          uuid NOT NULL REFERENCES scans (id) ON DELETE CASCADE,
  prompt_id        uuid NOT NULL REFERENCES prompts (id) ON DELETE CASCADE,
  engine           text NOT NULL,
  run              integer NOT NULL DEFAULT 1,
  brand            text,
  competitor_id    uuid REFERENCES competitors (id) ON DELETE SET NULL,
  mentioned        boolean NOT NULL DEFAULT false,
  position         integer,
  sentiment        text,
  sentiment_score  numeric,
  cited_urls       jsonb NOT NULL DEFAULT '[]'::jsonb,
  raw_response_ref text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mentions_account_scan_idx ON mentions (account_id, scan_id);
CREATE INDEX mentions_account_prompt_idx ON mentions (account_id, prompt_id);
CREATE INDEX mentions_scan_prompt_engine_idx ON mentions (scan_id, prompt_id, engine);
CREATE INDEX mentions_account_brand_idx ON mentions (account_id, brand);
CREATE INDEX mentions_created_at_idx ON mentions (created_at);
CREATE TRIGGER trg_mentions_updated_at BEFORE UPDATE ON mentions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- share_of_voice — PRE-COMPUTED aggregate per (scan, brand, engine).
-- Never computed live. engine = 'all' means the cross-engine aggregate.
-- ---------------------------------------------------------------------------
CREATE TABLE share_of_voice (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id    uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  scan_id       uuid NOT NULL REFERENCES scans (id) ON DELETE CASCADE,
  brand         text NOT NULL,
  competitor_id uuid REFERENCES competitors (id) ON DELETE SET NULL,
  is_self       boolean NOT NULL DEFAULT false,
  engine        text NOT NULL DEFAULT 'all',
  mention_count integer NOT NULL DEFAULT 0,
  mention_rate  numeric,
  avg_position  numeric,
  sov_pct       numeric,
  details       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX sov_scan_brand_engine_key ON share_of_voice (account_id, scan_id, brand, engine);
CREATE INDEX sov_account_scan_idx ON share_of_voice (account_id, scan_id);
CREATE TRIGGER trg_sov_updated_at BEFORE UPDATE ON share_of_voice
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- gaps — diagnosed problems per prompt/scan. gap_type is config taxonomy.
-- ---------------------------------------------------------------------------
CREATE TABLE gaps (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  scan_id    uuid REFERENCES scans (id) ON DELETE SET NULL,
  prompt_id  uuid REFERENCES prompts (id) ON DELETE SET NULL,
  gap_type   text NOT NULL,
  details    jsonb NOT NULL DEFAULT '{}'::jsonb,
  rank_score numeric,
  status     gap_status NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX gaps_account_status_idx ON gaps (account_id, status);
CREATE INDEX gaps_account_scan_idx ON gaps (account_id, scan_id);
CREATE TRIGGER trg_gaps_updated_at BEFORE UPDATE ON gaps
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- assets — generated outputs. type is config taxonomy; content stored
-- externally and referenced.
-- ---------------------------------------------------------------------------
CREATE TABLE assets (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id        uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  gap_id            uuid REFERENCES gaps (id) ON DELETE SET NULL,
  type              text NOT NULL,
  title             text,
  content_ref       text,
  metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
  target_prompt_ids uuid[] NOT NULL DEFAULT '{}',
  status            asset_status NOT NULL DEFAULT 'draft',
  validation_state  asset_validation_state NOT NULL DEFAULT 'pending',
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX assets_account_status_idx ON assets (account_id, status);
CREATE INDEX assets_target_prompts_idx ON assets USING gin (target_prompt_ids);
CREATE TRIGGER trg_assets_updated_at BEFORE UPDATE ON assets
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- verifications — did an asset move the needle? before/after metrics.
-- ---------------------------------------------------------------------------
CREATE TABLE verifications (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id     uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  asset_id       uuid NOT NULL REFERENCES assets (id) ON DELETE CASCADE,
  scan_before_id uuid REFERENCES scans (id) ON DELETE SET NULL,
  scan_after_id  uuid REFERENCES scans (id) ON DELETE SET NULL,
  before_metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  after_metrics  jsonb NOT NULL DEFAULT '{}'::jsonb,
  confidence     numeric,
  verdict        verification_verdict NOT NULL DEFAULT 'inconclusive',
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX verifications_account_asset_idx ON verifications (account_id, asset_id);
CREATE TRIGGER trg_verifications_updated_at BEFORE UPDATE ON verifications
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- verified_facts — authoritative pricing/features/naming. Generators MUST use
-- these instead of inventing facts. fact_type is config taxonomy.
-- ---------------------------------------------------------------------------
CREATE TABLE verified_facts (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id     uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  fact_type      text NOT NULL,
  key            text NOT NULL,
  value          jsonb NOT NULL,
  source         text,
  confidence     numeric,
  is_active      boolean NOT NULL DEFAULT true,
  effective_from timestamptz,
  effective_to   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX verified_facts_account_type_key_key ON verified_facts (account_id, fact_type, key);
CREATE INDEX verified_facts_account_type_idx ON verified_facts (account_id, fact_type);
CREATE TRIGGER trg_verified_facts_updated_at BEFORE UPDATE ON verified_facts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- jobs — pipeline job tracking. type/status drive the orchestrator.
-- external_id correlates to the Celery task id / BullMQ job id.
-- ---------------------------------------------------------------------------
CREATE TABLE jobs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id  uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  scan_id     uuid REFERENCES scans (id) ON DELETE SET NULL,
  type        text NOT NULL,
  status      job_status NOT NULL DEFAULT 'queued',
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  result      jsonb,
  error       text,
  attempts    integer NOT NULL DEFAULT 0,
  external_id text,
  started_at  timestamptz,
  finished_at timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_account_status_idx ON jobs (account_id, status);
CREATE INDEX jobs_status_idx ON jobs (status);
CREATE INDEX jobs_type_idx ON jobs (type);
CREATE TRIGGER trg_jobs_updated_at BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- audit_logs — immutable who/what/when (esp. key access + publishing).
-- Append-only: created_at only, no updated_at. bigint identity for volume.
-- ---------------------------------------------------------------------------
CREATE TABLE audit_logs (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id    uuid REFERENCES accounts (id) ON DELETE SET NULL,
  actor_type    text NOT NULL,
  actor_id      text,
  action        text NOT NULL,
  resource_type text,
  resource_id   text,
  metadata      jsonb NOT NULL DEFAULT '{}'::jsonb,
  ip            inet,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_logs_account_created_idx ON audit_logs (account_id, created_at);
CREATE INDEX audit_logs_action_idx ON audit_logs (action);

-- ---------------------------------------------------------------------------
-- llm_cost_log — per-call cost/usage. Append-only: created_at only.
-- bigint identity for volume.
-- ---------------------------------------------------------------------------
CREATE TABLE llm_cost_log (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id        uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  job_id            uuid REFERENCES jobs (id) ON DELETE SET NULL,
  scan_id           uuid REFERENCES scans (id) ON DELETE SET NULL,
  provider          text NOT NULL,
  model             text NOT NULL,
  operation         text,
  prompt_tokens     integer NOT NULL DEFAULT 0,
  completion_tokens integer NOT NULL DEFAULT 0,
  total_tokens      integer NOT NULL DEFAULT 0,
  cost_usd          numeric(12, 6) NOT NULL DEFAULT 0,
  mock              boolean NOT NULL DEFAULT false,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_cost_log_account_created_idx ON llm_cost_log (account_id, created_at);
CREATE INDEX llm_cost_log_job_idx ON llm_cost_log (job_id);
CREATE INDEX llm_cost_log_model_idx ON llm_cost_log (model);
