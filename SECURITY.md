# Security checklist

Where each control lives, and what is deliberately deferred to deployment or a
later phase. "Covered" means it exists in code on `main` and is exercised by the
test suite; "Deployment" means it's an infra/ops responsibility with a code hook
ready; "Deferred" is tracked in [SCALING.md](SCALING.md) or noted below.

Verified end-to-end by `services/pipeline/tests/test_full_loop.py` — the whole
Monitor → Diagnose → Plan+Execute → Verify loop runs on the demo account in mock
mode with every guard active.

## Application security — covered

| Control | Where |
| --- | --- |
| **Tenant isolation** — `account_id` on every row and every query; no IDOR | Repository layers: [apps/api/src/repositories](apps/api/src/repositories/) (Drizzle) + [services/pipeline/app/db/repositories](services/pipeline/app/db/repositories/) (SQLAlchemy). Session → `accountId`; internal routes validate the row belongs to the tenant. |
| **CMS credentials encrypted at rest**, write-only, never returned or logged | Envelope encryption [apps/api/src/crypto/envelope.ts](apps/api/src/crypto/envelope.ts); routes are write-only, list/read return metadata only ([routes/cms-credentials.ts](apps/api/src/routes/cms-credentials.ts)). |
| **Internal TS↔Python auth** — shared secret, constant-time compare | [apps/api/src/internal/pipeline-client.ts](apps/api/src/internal/pipeline-client.ts) sends `x-internal-secret`; [services/pipeline/app/core/security.py](services/pipeline/app/core/security.py) verifies with `hmac.compare_digest`. |
| **CORS** locked to the frontend origin (never `*`) | [apps/api/src/server.ts](apps/api/src/server.ts) — `FRONTEND_ORIGIN`, `credentials: true`. |
| **Security headers** — CSP (`default-src 'none'`), HSTS (180d), frameguard deny | `@fastify/helmet` in [server.ts](apps/api/src/server.ts). |
| **Rate limits** — Redis-backed global ceiling + stricter auth routes | `@fastify/rate-limit` (shared across instances) in [server.ts](apps/api/src/server.ts). |
| **Plan quotas** — gate + double-check | TS middleware ([apps/api/src/plans.ts](apps/api/src/plans.ts)); the pipeline **re-checks** before any expensive job ([services/pipeline/app/pipeline/quota.py](services/pipeline/app/pipeline/quota.py), config [quotas.yaml](services/pipeline/config/quotas.yaml)). |
| **Validation at every boundary** | Zod + a 400 error handler ([apps/api/src/validate.ts](apps/api/src/validate.ts), [server.ts](apps/api/src/server.ts)); Pydantic models with `extra="forbid"` throughout the pipeline. |
| **Output sanitization** on generated HTML (XSS) | `nh3.clean` strips scripts/dangerous attrs in [validate.py](services/pipeline/app/pipeline/execution/validate.py); asserted script-free in the execution + full-loop tests. |
| **Verified-facts enforcement** — no hallucinated customer claims | Every `self` claim must match an active `verified_fact` or the asset is rejected ([validate.py](services/pipeline/app/pipeline/execution/validate.py)). |
| **SSRF guard + fetch caps** on all scraping | `assert_public_url` on every request and redirect hop; timeout / max-redirects / max-bytes caps ([ssrf.py](services/pipeline/app/pipeline/diagnosis/ssrf.py), [fetcher.py](services/pipeline/app/pipeline/diagnosis/fetcher.py)). Scraped content is untrusted data, never fed to a model as instructions. |
| **No raw SQL** — ORM / parameterized only | Drizzle (TS) and SQLAlchemy (Python) everywhere; no string-built queries. |
| **Secrets in env, gitignored, never logged** | [config.ts](apps/api/src/config.ts) / [config.py](services/pipeline/app/core/config.py) validate at boot and are never logged; error handlers surface field names, not values. |
| **Audit log** — immutable who/what/when for key access + writes | `audit_logs` table; [AuditRepository](apps/api/src/repositories/audit-repository.ts) is called on CMS-credential create/delete, auth, account, and scan actions. |
| **Retries / backoff** on external calls | Gateway retry-with-backoff + per-provider token-bucket rate limiting ([app/gateway](services/pipeline/app/gateway/)); scraper caps as above. |
| **Job status + error capture** | Scan lifecycle `pending → running → completed/failed` with error text ([scan.py](services/pipeline/app/db/repositories/scan.py)); per-call spend in `llm_cost_log`. |
| **Structured logging, no secrets/PII** | pino via Fastify (TS); stdlib logging configured in [observability.py](services/pipeline/app/core/observability.py) — we log ids/counts/status only. |
| **Error tracking (Sentry)** — off unless `SENTRY_DSN` set; PII off + scrubber | [apps/api/src/observability.ts](apps/api/src/observability.ts) and [services/pipeline/app/core/observability.py](services/pipeline/app/core/observability.py). |
| **Cost visibility** | Every model call logs to `llm_cost_log`; surfaced via `GET /internal/costs` (shared-secret) — mock vs real split + per-model breakdown. |
| **Mode switch** mock → dev → prod via env only, no code change | `GATEWAY_MODE` selects providers from [models.yaml](services/pipeline/config/models.yaml); the whole suite runs in `mock` with no keys. |
| **Secret scanning + dependency audit in CI** | [.github/workflows/ci.yml](.github/workflows/ci.yml): gitleaks ([.gitleaks.toml](.gitleaks.toml)), `pnpm audit`, `pip-audit`; weekly [Dependabot](.github/dependabot.yml). |

## Deployment-owned (code hook ready, set at deploy time)

- **HTTPS/TLS everywhere** — terminate at the edge/load balancer; HSTS is already sent. `trustProxy` is on so client IPs are honoured behind a proxy.
- **Cloudflare in front** — DDoS protection + WAF as the edge layer.
- **Encrypted DB backups** + **managed Postgres/Redis** in prod (point-in-time recovery).
- **Master key in a KMS** — envelope encryption already supports `keyVersion`/rotation; today the KEK is env-provided (`MASTER_ENCRYPTION_KEY`), swap for a KMS-issued key in prod.
- **Real API keys** added to the environment at deploy (still never committed). Flip `GATEWAY_MODE=dev`, run one real call per task to confirm wiring, then leave tests on `mock`.

## Deferred / follow-up

- **Least-privilege CMS token scopes** — credentials are stored write-only now; the minimum publish scope is enforced when the CMS **publish** integrations are built (not yet in the pipeline).
- **Versioned generators** — generators are deterministic/idempotent given the same gap + verified facts, but are not yet version-stamped on the asset; add a `generator_version` tag when a generator's output format changes.
- **Scaling** — partitioning, read replicas, TimescaleDB, roll-up/archival, multi-key, multi-region, sharding: see [SCALING.md](SCALING.md).
