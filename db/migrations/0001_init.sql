-- 0001_init.sql — base extensions for the GEO SaaS schema.
--
-- The DB schema is the CONTRACT between the TS API and the Python pipeline.
-- It changes ONLY via numbered migrations in this directory. No business
-- tables yet (Phase 1) — this just enables the extensions later phases need.
--
-- In local dev, infra/docker-compose.yml mounts this directory into Postgres's
-- /docker-entrypoint-initdb.d, so these run automatically on first boot.

-- Vector similarity search (embeddings for retrieval/diagnosis).
CREATE EXTENSION IF NOT EXISTS vector;

-- gen_random_uuid() and other crypto helpers for primary keys.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Convention reminder for later migrations: every business table is
-- multi-tenant — it carries account_id, and every query filters on it.
