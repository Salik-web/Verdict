# Database Schema — the service contract

This is the reference for the shared Postgres schema. **The SQL migrations in
[`db/migrations`](migrations/) are the single source of truth.** The Drizzle
schema ([`apps/api/src/db/schema.ts`](../apps/api/src/db/schema.ts)) and the
SQLAlchemy models ([`services/pipeline/app/db/models.py`](../services/pipeline/app/db/models.py))
are hand-written mirrors — when a migration changes the schema, update both.

## How migrations are applied

Numbered `NNNN_*.sql` files, applied in order by the runner, which records
applied versions in `schema_migrations` and is idempotent:

```bash
pnpm --filter @geo/api db:migrate   # apply pending migrations
pnpm --filter @geo/api db:seed      # load the demo account (idempotent)
```

| Migration              | Purpose                                                            |
| ---------------------- | ------------------------------------------------------------------ |
| `0001_init.sql`        | Extensions: `vector` (pgvector), `pgcrypto` (`gen_random_uuid()`). |
| `0002_core_schema.sql` | Enums, `set_updated_at()` trigger, all core tables + indexes.      |

## Conventions

- **Multi-tenant:** every table except `accounts` carries `account_id` (FK →
  `accounts`, `ON DELETE CASCADE`) and is indexed on it. Repositories filter by
  `account_id` on every query; `accounts` is the tenant root.
- **Primary keys:** `uuid` via `gen_random_uuid()`, **except** the high-volume
  tables `mentions`, `audit_logs`, `llm_cost_log`, which use `bigint GENERATED
ALWAYS AS IDENTITY` for index locality.
- **Timestamps:** `created_at` + `updated_at` (the latter maintained by the
  `set_updated_at` trigger) on every table, **except** the append-only logs
  `audit_logs` and `llm_cost_log`, which carry `created_at` only.
- **Enums vs text:** lifecycle state machines are Postgres `ENUM`s (DB-enforced).
  Open taxonomies that live in config — `engine`, `gap_type`, `category`,
  `asset.type`, `verified_facts.fact_type` — are free `text`, never hardcoded as
  enums.
- **Big/raw payloads** (raw model responses, generated content) are stored
  externally and referenced by `*_ref` columns; structured extras live in
  `jsonb`.
- **Embeddings:** the `vector` extension is enabled, but no embedding columns
  exist yet — they'll be added in the phase that consumes them (so the dimension
  is chosen with the embedding model).

## Enums

| Type                     | Values                                           |
| ------------------------ | ------------------------------------------------ |
| `user_role`              | owner, admin, member                             |
| `scan_status`            | pending, running, completed, failed, canceled    |
| `job_status`             | queued, running, succeeded, failed, canceled     |
| `gap_status`             | open, planned, in_progress, resolved, dismissed  |
| `asset_status`           | draft, generated, validated, published, rejected |
| `asset_validation_state` | pending, passed, failed                          |
| `verification_verdict`   | improved, no_change, regressed, inconclusive     |

## Tables

### accounts — tenant root

Company/tenant. Tracks own brand (`brand_name`, `brand_aliases`) for share of
voice, plus plan/subscription fields (`plan`, `subscription_status`,
`trial_ends_at`, `current_period_end`, `stripe_customer_id`,
`stripe_subscription_id`). `slug` is unique. No `account_id`.

### users — belong to an account

`email` (globally unique, case-insensitive), `role` (`user_role`),
`password_hash`, `status`, `last_login_at`.

### competitors — tracked brands per account

External competitors and, with `is_self = true`, the account's own brand (so all
tracked brands are rows for share-of-voice math). `aliases text[]`. Unique on
`(account_id, lower(name))`.

### prompts — tracked questions

`text`, `category`, `prompt_group`, `active`. Indexed on `(account_id, active)`.

### scans — one measurement run

`status` (`scan_status`), `engine_set jsonb` (snapshot of engines/models
covered), `started_at`/`finished_at`, `stats jsonb`, `triggered_by`, `error`.

### mentions — TIME-SERIES (largest table)

One row per `(scan, prompt, engine, run)`. `bigint` identity PK. Columns:
`engine`, `run`, `brand`, `competitor_id` (matched brand, nullable),
`mentioned`, `position`, `sentiment`/`sentiment_score`, `cited_urls jsonb`,
`raw_response_ref` (pointer to externally stored raw response). Indexed on
`(account_id, scan_id)`, `(account_id, prompt_id)`, `(scan_id, prompt_id,
engine)`, `(account_id, brand)`, `(created_at)`. Designed for volume; range
partitioning on `created_at`/`scan_id` is the next lever when needed.

### share_of_voice — pre-computed aggregate (never live)

One row per `(scan, brand, engine)`; `engine = 'all'` is the cross-engine
aggregate. `mention_count`, `mention_rate`, `avg_position`, `sov_pct`,
`is_self`. Unique on `(account_id, scan_id, brand, engine)`.

### gaps — diagnosed problems

`gap_type` (config taxonomy), `details jsonb`, `rank_score`, `status`
(`gap_status`); optional `scan_id`/`prompt_id`.

### assets — generated outputs

`type` (config taxonomy), `title`, `content_ref` (external content),
`metadata jsonb`, `target_prompt_ids uuid[]` (GIN-indexed), `status`
(`asset_status`), `validation_state` (`asset_validation_state`), optional
`gap_id`.

### verifications — did an asset move citations?

`asset_id`, `scan_before_id`/`scan_after_id`, `before_metrics`/`after_metrics`
jsonb, `confidence`, `verdict` (`verification_verdict`).

### verified_facts — authoritative source of truth

`fact_type` (config taxonomy), `key`, `value jsonb`, `source`, `confidence`,
`is_active`, `effective_from`/`effective_to`. Unique on `(account_id, fact_type,
key)`. Generators MUST use these rather than inventing facts.

### jobs — pipeline job tracking

`type`, `status` (`job_status`), `payload`/`result` jsonb, `error`, `attempts`,
`external_id` (Celery task / BullMQ id), `started_at`/`finished_at`, optional
`scan_id`.

### audit_logs — immutable who/what/when (append-only)

`actor_type`/`actor_id`, `action` (e.g. `key.access`, `asset.publish`),
`resource_type`/`resource_id`, `metadata jsonb`, `ip inet`, `created_at`.

### llm_cost_log — per-call usage/cost (append-only)

`provider`, `model`, `operation`, `prompt_tokens`/`completion_tokens`/
`total_tokens`, `cost_usd numeric(12,6)`, `mock` (was it a mock call), optional
`job_id`/`scan_id`, `created_at`.
