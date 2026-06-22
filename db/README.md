# db — schema (single source of truth)

The Postgres schema is the **contract** between the TypeScript API and the
Python pipeline. It changes **only** through numbered SQL migrations here.

## Migrations

- Files are `NNNN_description.sql`, applied in ascending order.
- Each is forward-only and idempotent where practical (`IF NOT EXISTS`).
- In local dev, [`infra/docker-compose.yml`](../infra/docker-compose.yml) mounts
  this directory into Postgres's `/docker-entrypoint-initdb.d`, so migrations
  run automatically the **first** time the database volume is created.

To re-run from scratch locally:

```bash
cd infra
docker compose down -v   # drops the volume
docker compose up -d     # re-runs all migrations on fresh init
```

> A real migration runner (e.g. Drizzle on the TS side) gets wired in a later
> phase. For now the init-dir mount is enough for the Phase 1 checkpoint.

## Conventions

- **Multi-tenant from day one:** every business table carries `account_id`, and
  every query filters on it.
- Primary keys via `gen_random_uuid()` (pgcrypto).
- `vector` columns (pgvector) for embeddings.

| Migration | Purpose |
| --- | --- |
| [`0001_init.sql`](migrations/0001_init.sql) | Enable `vector` + `pgcrypto` extensions. |
