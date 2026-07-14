# Scaling — cheap insurance now, heavy machinery deferred

The backend is built to scale horizontally without a rewrite. This file records
what's already in place, and what we deliberately **defer until load demands it**
(building it early is cost with no payoff). Add a dated note here when you pick
one up.

## In place now (cheap insurance)

- **Stateless services.** The Fastify API and the Celery workers hold no local
  state — sessions live in Redis, jobs in Redis+Postgres. Add instances and the
  queue distributes; ready for autoscaling behind a load balancer.
- **Aggregates pre-computed, never live.** `share_of_voice` is written at scan
  time from the raw `mentions`; dashboards read the roll-up, not a live GROUP BY
  over the time series. Verification reads the same pre-computed shape.
- **Hot tables indexed for tenant + time.** `mentions`, `scans`,
  `share_of_voice`, `gaps`, `audit_logs`, `llm_cost_log` are indexed on
  `(account_id, …)` / `(account_id, created_at)`. High-volume logs use `bigint`
  identity PKs for index locality.
- **Shared, managed-ready datastores.** One Postgres is the spine; Redis is the
  broker/cache. Both move to managed instances (RDS/Cloud SQL, ElastiCache/
  Memorystore) in prod with no code change — only connection strings.
- **Backpressure built in.** Per-provider token-bucket rate limiting and a
  response cache in the gateway; per-account plan quotas gate expensive jobs on
  both sides. Cost is logged per call (`llm_cost_log`) so spend is observable.
- **Jittered scheduling.** Periodic scans spread across a window (deterministic
  per-account offset) so a cohort never stampedes the workers at once.

## Deferred — build only when the numbers say so

| Item | Trigger to build it | Note |
| --- | --- | --- |
| **Time/tenant partitioning** of `mentions` (and other logs) | Single-table scans/writes start to hurt (tens of millions of rows) | Schema already isolates the log tables; partition by `created_at` range and/or `account_id` hash. |
| **Read replicas** for dashboard reads | Read load competes with write/ingest load | Aggregates are already read-mostly; point dashboard reads at a replica. |
| **TimescaleDB** (or similar) for `mentions` | Time-series queries dominate and hypertables clearly win | `mentions` is already an append-only time series with a time index. |
| **Raw-data roll-up + archival** | Storage cost of raw mentions outgrows its value | Keep recent raw, roll older into periodic aggregates, cold-store the rest. |
| **Multiple provider accounts/keys** | A single provider account's rate limit becomes the ceiling | Gateway already abstracts providers; add key rotation/sharding behind it in config. |
| **Redis caching for hot reads** (beyond the gateway cache) | A specific hot read shows up in profiling | Cache is a swap-in at the repository boundary; add per-endpoint TTLs. |
| **Multi-region** | Latency/residency requirements appear | Stateless services make this mostly a data-layer + edge problem. |
| **Sharding Postgres by tenant** | One primary can't hold the write volume | Last resort; every table already carries `account_id`, so tenant-sharding is tractable. |

## Related

Security controls and what's owned by deployment: [SECURITY.md](SECURITY.md).
