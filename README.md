# GEO — AI visibility monitoring

**Find out whether ChatGPT, Gemini, Perplexity and Claude recommend your brand — and diagnose why they don't.**

GEO asks AI engines the questions your buyers actually ask, records which brands they name, then audits your site for the reasons you're missing. Monitoring and diagnosis, end to end.

```bash
git clone https://github.com/Salik-web/Geo.git
cd Geo
cp .env.example .env
docker compose up
```

Open **http://localhost:5173**. That's it — Postgres, Redis, migrations, the API, the pipeline, a worker and the UI. Cold start takes about 15 seconds, needs **no API keys**, and costs nothing: the default `GATEWAY_MODE=mock` runs the whole pipeline against fixtures.

![Leaderboard from a live Gemini scan: 46 brands the engine named, ranked by share of voice. The user's own brand, ImagineArt, sits at 0.0% and rank #46 — shown explicitly rather than omitted — with a callout reading "ImagineArt was not named in any answer. That is the measurement, not an error." Competitors the user never configured are flagged "discovered"; configured ones are flagged "tracked".](docs/images/leaderboard.png)

*A real scan against live Gemini: 10 answers, 46 brands named, and the customer absent from all of them. Being at 0% is the finding — so the row is shown, not hidden.*

---

## The principle: never assert an absence you didn't establish

Most of this codebase exists to avoid one failure: **confidently telling you something false.** A monitoring tool that invents a problem is worse than one that reports nothing, because you'll act on it.

So every check distinguishes *"I looked and it wasn't there"* from *"I couldn't look."*

| Situation | Naive tool says | GEO says |
| --- | --- | --- |
| Page returns **403** | "your brand is absent from this page" | `check_failed` — we were refused, we learned nothing |
| Response **truncated** at the byte cap | "no schema found" | absence downgraded — *"only 2.9 MB of 4 MB analysed, so this absence is not established"* |
| Engine returns an **empty answer** | `mentioned=false` — a data point against you | dropped as a failed observation; `observations_used` < `observations_requested`, and both are reported |
| Citations are **redirect wrappers** | fetches them, finds nothing, raises a gap | `check_failed` — a `vertexaisearch` redirect says nothing about the publisher behind it |
| Homepage **fetch times out** | three gaps from one failed fetch | one honest `page_fetch_failed`; the checks that need no HTTP still run |

The corollary matters as much: **a passing check must be as auditable as a failing one.** When GEO says "you have comparison pages," it records how it knows — which robots.txt directive it read, which sitemap it fetched, the HTTP status, how many URLs it parsed, how many matched, and the regex it matched them with. You can re-derive the verdict by hand.

## Why it's built this way

Every rule above comes from a real defect found by auditing this project against ground truth. They are worth stating plainly, because they're the failure modes any tool in this space will have:

| Defect found | Consequence |
| --- | --- |
| Fabricated share of voice | **13 of 13 brands** in the leaderboard appeared nowhere in the answers they were attributed to |
| False "no comparison page" gap, scored **0.81** and ranked #1 | The site had **85 comparison URLs** (measured 2026-08-05; 93 by 2026-08-17 — it keeps publishing them). The check read only the homepage and reported a site-wide verdict |
| One failed fetch → **three confident gaps** | Missing schema, no H1, no comparison page — all inferred from a page that never loaded |
| Cost ledger **~40% short** | Cache hits and failed calls weren't logged; the generation call omitted `scan_id`, so per-scan cost silently undercounted |
| `noindex` detected, then **silently dropped** | The most severe finding the tool can produce never reached the user |
| Parser recall **31.8%** | An 8B model recalled a third of the brands the engines named. Share of voice was computed on a third of the market |

The last one is the pattern in miniature: the fix was a better model (**31.8% → 96.9%**, measured on a committed fixture of 129 brand-mentions, `tests/fixtures/parser_recall.json`), but the *finding* only existed because someone checked the output against the source text instead of trusting it.

## Engines

Bring your own keys. You need **at most one** — an engine with no key is reported unavailable and skipped, so a single key gives you a working single-engine scan.

| Engine | Grounding billed | Per grounded call | 10-call scan | Free tier | Status |
| --- | --- | --- | --- | --- | --- |
| **Gemini** 2.5 Flash | per prompt | $0.035 | $0.35 | ~20 req/day/model ≈ **2 scans/day** | **Verified live** |
| **Perplexity** Sonar | per request, by context size | $0.005–0.012 | **$0.05–0.12** | none — $50 minimum | Unverified |
| **OpenAI** GPT-4.1 (Responses API) | per tool call | $0.010 | $0.10 | none | Unverified |
| **Claude** (Messages API) | **per search** | $0.010 | $0.10+ | none | Unverified |

**Verified live** means it has made real calls from this codebase. **Unverified** means the adapter was written against published documentation and is covered by unit tests using recorded response shapes, but has never made a real call — each such adapter says so in a banner at the top of its own file. Treat your first live scan as its acceptance test.

**Evaluate on Gemini** (the only free path). **Run on Perplexity** (3–7× cheaper per request, but no free tier). Claude and OpenAI bill *per search*, and one request can run several — `max_searches` caps it.

Grounding is mandatory. An ungrounded answer is training-data recall: it tells you what a model absorbed months ago, cites nothing, and leaves the entire diagnosis layer inert. An engine that can't ground doesn't ship.

Full detail, with source links: **[docs/ENGINES.md](docs/ENGINES.md)**.

## What it doesn't do

- **No content generation.** GEO measures, diagnoses, and *ranks* your fixes. It does not write them. The `Generator` interface, the registry, the verified-facts gate and the claim validator are all here — the concrete generators are not. Planning still runs; the UI shows the ranked backlog with an explicit *"no generator available for this fix type"* state rather than a button that does nothing. To add your own: **[docs/WRITING-A-GENERATOR.md](docs/WRITING-A-GENERATOR.md)**.
- **Most site checks read the homepage only.** Schema, headings, freshness and quotability are single-page. Only the comparison-page check is site-wide (via sitemap). Single-page inferences are recorded at low confidence and never ranked as your top fix.
- **Costs are modelled, not billed.** Every call is priced from `config/models.yaml`, so a call served by a free tier still shows its list price. Useful for unit economics; it is not your invoice.
- **Three of four engines are unverified.** See the table above.

Full list: **[docs/LIMITATIONS.md](docs/LIMITATIONS.md)**.

## Setup

The defaults work with no configuration. To measure real engines:

```bash
# 1. add a key to .env
GATEWAY_MODE=dev
GOOGLE_API_KEY=...          # or PERPLEXITY_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY

# 2. uncomment the matching engine in services/pipeline/config/monitor.yaml
# 3. restart — config is read at import
docker compose restart worker pipeline
```

Then, in the UI: **Setup** → set your domain and category → **Generate prompts** → **Run a scan**.

Cost scales directly with active prompts: each one is 5 grounded calls per engine, per scan. The Setup page shows the arithmetic before you spend anything.

Running the services directly on a host instead of in containers: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**, which also covers multi-tenant key management if you're building a product on top.

## Stack

| Path | Service | Stack |
| --- | --- | --- |
| [`apps/api`](apps/api/) | TypeScript API | Fastify, Drizzle, Zod |
| [`apps/web`](apps/web/) | UI | Next.js, Tailwind |
| [`services/pipeline`](services/pipeline/) | Python pipeline | FastAPI, Celery, LangGraph, SQLAlchemy |
| [`db`](db/) | Schema | SQL migrations — the source of truth |

Two services over one shared Postgres. **The database schema is the contract between them.** Every model call goes through a gateway where the task→model mapping, pricing, retries, caching and rate limits live in config, not code — adding an engine is a config edit plus an adapter file, never a change to the gateway.

## Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)**. The short version: explain *why* in comments, keep config in config, and if you add a check, record its working so a passing verdict is as auditable as a failing one.

```bash
cd services/pipeline && uv run pytest        # 328 tests
cd apps/api && npx tsc --noEmit && node --import tsx --test src/tests/*.test.ts
```

## Licence

**AGPL-3.0-or-later.** Self-hosting, internal use and personal use carry **no obligations** — run it, modify it, keep your changes private. The copyleft obligation applies only if you offer a *modified* version as a network service to others, in which case you must publish your modifications.

Generators are a separate concern: the `geo.generators` entry point means a private generator package is not a derivative work of this repository.
