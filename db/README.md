# db — schema (single source of truth)

The Postgres schema is the **contract** between the TypeScript API and the
Python pipeline. It changes **only** through numbered SQL migrations here.

See [SCHEMA.md](SCHEMA.md) for the full table-by-table contract reference.

## Migrations

- Files are `NNNN_description.sql`, applied in ascending order.
- Each is forward-only and idempotent where practical (`IF NOT EXISTS`).
- Applied by the runner, which records applied versions in a
  `schema_migrations` table and skips already-applied files:

```bash
pnpm --filter @geo/api db:migrate   # apply pending migrations
pnpm --filter @geo/api db:seed      # load the demo account (idempotent)
```

To re-run from a clean database:

```bash
cd infra && docker compose down -v && docker compose up -d   # fresh volume
pnpm --filter @geo/api db:migrate && pnpm --filter @geo/api db:seed
```

The Drizzle schema (`apps/api/src/db/schema.ts`) and SQLAlchemy models
(`services/pipeline/app/db/models.py`) are hand-written **mirrors** of these SQL
files — update them together. Drizzle never generates the SQL.

## Conventions

- **Multi-tenant from day one:** every table except `accounts` carries
  `account_id`, indexed, and every query filters on it.
- UUID PKs via `gen_random_uuid()`, except high-volume tables (`mentions`,
  `audit_logs`, `llm_cost_log`) which use `bigint` identity.
- `created_at`/`updated_at` everywhere except the append-only logs.
- `vector` (pgvector) extension is enabled for embeddings; embedding columns are
  added in the phase that consumes them.

| Migration                                                         | Purpose                                                     |
| ----------------------------------------------------------------- | ----------------------------------------------------------- |
| [`0001_init.sql`](migrations/0001_init.sql)                       | Enable `vector` + `pgcrypto` extensions.                    |
| [`0002_core_schema.sql`](migrations/0002_core_schema.sql)         | Enums, `set_updated_at` trigger, all core tables + indexes. |
| [`0003_cms_credentials.sql`](migrations/0003_cms_credentials.sql) | Envelope-encrypted CMS credentials table.                   |
