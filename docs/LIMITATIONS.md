# What this doesn't do

An honest inventory of what is excluded, unverified, or incomplete, so nobody
discovers it the hard way. Written for the README to draw from.

## Deliberately excluded

**Content generation.** The pipeline monitors, diagnoses, and *ranks* fixes. It
does not write them. The `Generator` interface, the registry, the
verified-facts gate, the placeholder filter, and the claim validator are all
here — the concrete generators are not, and are the commercial layer. Planning
still runs and the ranked backlog is real output; the UI shows it with an
explicit "no generator available for this fix type" state rather than a button
that does nothing. See `docs/WRITING-A-GENERATOR.md`.

**Dark mode.** Light only. Doubles the UI surface for no adoption benefit.

**A design system.** `apps/web` is default Tailwind with no component library.
It aims at "a competent developer would trust this", not at visual polish.

## Unverified

**Three of four engines have never made a live call.** Gemini 2.5 Flash is
verified — it ran every real scan during development. Perplexity, OpenAI and
Claude were implemented against published documentation and are covered by unit
tests using recorded response *shapes*. They are wired, priced, rate-limited and
gated on their keys, but the first real scan is their acceptance test. Each
unverified adapter says so at the top of its own file. See `docs/ENGINES.md`.

Two specific unknowns worth closing early, both settled by a single live call:

- **Perplexity citation shape.** Whether `search_results[].url` returns direct
  publisher URLs or redirect wrappers is not documented. The pipeline handles
  both, but the answer decides how much the third-party-presence check can
  conclude for that engine.
- **Perplexity search context size.** The per-request retrieval fee is $5/$8/$12
  per 1,000 depending on context size. We do not send
  `web_search_options.search_context_size`, so the live tier is Perplexity's
  default; `config/models.yaml` prices at medium as an estimate. The response
  echoes the actual value back in `usage`.

**Grounding vs structured output** is confirmed incompatible on Gemini 2.5 only.
Not tested for the other three. It does not currently matter — no measurement
task asks for JSON — but it would if you added one.

## Known limitations

**Entity resolution splits some brands.** `normalize()` treats `.` as an
internal character and `_bases()` splits on spaces only, so a dotted TLD-style
suffix is not recognised as a variant tail:

- `Leonardo.ai` and `Leonardo AI` stay separate rows
- `ArtSmart.ai` and `ArtSmart` stay separate
- `Veo 3` and `Google Veo 3` stay separate (the vendor is a *prefix*; only
  suffixes are stripped)

Casing and trailing parentheticals *are* handled. The consequence is that a
brand's share of voice can be split across two rows, understating it.

**Extraction over-counts vendors and ecosystem names.** Parent companies and
adjacent products mentioned in passing (`Adobe` alongside `Adobe Firefly`,
`Photoshop`, `Creative Cloud`, `OpenAI`) are sometimes extracted as if they were
recommended tools. They inflate the leaderboard denominator and slightly
understate everyone else's share.

**Body-presence checking needs resolvable URLs.** When every citation is a
redirect wrapper — which is the normal case for Gemini — the check reports
`check_failed` rather than a gap. This is correct, not a bug, but it means the
`missing_from_listicles` gap is only reachable on engines that return real
publisher URLs. The domain-level check (`cited_domains`) works regardless.

**The AI-bot audit's passing verdict is not persisted as a finding.**
`stats.blocked_search_bots` records the result, but no row lands in
`diagnosis_findings`, so that particular "no problem here" is less auditable
than the others. Known gap, not yet closed.

**`schema_present` records only a URL.** Unlike the sitemap and citation checks,
it does not record how many JSON-LD blocks it found, their `@type`, or whether
they parse. A passing verdict there is not re-derivable from the record.

**No public-suffix list.** `registrable_domain()` uses a small hard-coded set of
two-label suffixes. An unusual ccTLD may group two subdomains that should be
separate. The worst case is a slightly wrong domain histogram.

**Re-running diagnosis on the same scan duplicates its gaps.** `POST
/internal/diagnoses/run` inserts a fresh set without clearing the previous one,
so a scan re-diagnosed three times shows each gap three times. The normal
pipeline runs diagnosis once per scan and is unaffected; this only bites when
re-running a stage by hand.

**The Costs page needs server-side configuration outside Docker.** It is the one
screen that proxies through a Next.js server route (the pipeline's cost endpoint
is shared-secret guarded, and that secret must never reach the browser). Under
`docker compose` this is wired for you. Running the UI directly on a host, you
must set `API_INTERNAL_URL`, `PIPELINE_INTERNAL_URL` and
`INTERNAL_SHARED_SECRET` for that page to load; every other screen calls the API
from the browser and needs nothing.

**In-memory gateway cache.** Per-process, so Celery workers do not share it.
Fine at one worker; add a Redis-backed cache before scaling out.

**Cost figures are modelled, not billed.** `llm_cost_log` prices every call from
`config/models.yaml`, so a call served by a free tier still shows its list
price. Useful for unit economics, not an invoice. There is no "was free-tier"
flag.

## A note on the defect table in the README

Those defects were found by auditing this project against ground truth, and the
fixes are all covered by tests you can run. Two numbers in that table come from
audit runs whose raw data no longer exists (the development database was wiped
during release testing), so they cannot be re-derived from this repository
today: the "13 of 13 brands" fabrication and the "~40% short" cost ledger. The
regressions they produced ARE pinned by tests — `test_guard.py`,
`test_parser_recall.py`, `test_cost_completeness.py` — but if you want the
original measurements rather than the guarantees, they are not reproducible
here. The parser-recall figures (31.8% / 96.9%) are the exception: their fixture
is committed at `services/pipeline/tests/fixtures/parser_recall.json`.

## Operational notes

**A demo password appears in git history** (commit `9110592`, in `db/seed.sql`
and `apps/web/README.md`). It is fixed at HEAD — the seed now generates a random
password and prints it once — but the history retains it. It only ever unlocked
a local demo account created by running `db:seed` against your own database. If
you ever ran that seed against a reachable environment, rotate.

**Verification requires a shipped asset.** With no generators registered nothing
is produced, so the verification loop has nothing to verify unless you register
a generator or create an asset yourself. The machinery and its honest verdicts
(`no_change`, `inconclusive`) are fully present and tested.

**Free-tier ceilings are low.** Gemini's ~20 requests/day/model works out to
about two scans a day at default settings. That is enough to evaluate the
product and not enough to run it. Perplexity is 3–7× cheaper per request but has
no free tier at all ($50 minimum). See `docs/ENGINES.md`.
