-- 0001_init.sql — base extensions for the GEO SaaS schema.
--
-- The DB schema is the CONTRACT between the TS API and the Python pipeline.
-- It changes ONLY via numbered migrations in this directory. No business
-- tables yet (Phase 1) — this just enables the extensions later phases need.
--
-- Migrations are applied by the runner (apps/api: `pnpm db:migrate`), which
-- records applied versions in a schema_migrations table and is idempotent.

-- Vector similarity search (embeddings for retrieval/diagnosis).
CREATE EXTENSION IF NOT EXISTS vector;

-- gen_random_uuid() and other crypto helpers for primary keys.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Convention reminder for later migrations: every business table is
-- multi-tenant — it carries account_id, and every query filters on it.
