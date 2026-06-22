# infra — local dev infrastructure

[`docker-compose.yml`](docker-compose.yml) brings up the two stateful
dependencies both services share:

- **Postgres 16 + pgvector** (`pgvector/pgvector:pg16`) — the shared DB / contract
  spine. Migrations in [`../db/migrations`](../db/migrations) run automatically on
  first boot.
- **Redis 7** — Celery broker/backend (pipeline) and BullMQ (API).

## Usage

```bash
cd infra
cp .env.example .env
docker compose up -d
docker compose ps          # both services healthy
docker compose logs -f     # tail logs
docker compose down        # stop (keep data)
docker compose down -v     # stop + wipe volumes (re-runs migrations next up)
```

Defaults: Postgres on `localhost:5432` (`geo`/`geo`, db `geo`), Redis on
`localhost:6379`. Override via [`.env`](.env.example).
