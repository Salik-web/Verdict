# Contributing

Thanks for looking. This project has a strong opinion about one thing, and
almost no opinions about the rest.

## The one opinion: never assert an absence you did not establish

Most of this codebase is a monitoring and diagnosis tool, and the failure mode
that matters is not a crash — it is **confidently telling a user something
false**. A gap that says "your brand is missing from these pages" when the
fetch returned 403, or "no comparison page found" when the check only read the
homepage, is worse than no output at all, because a user will act on it.

So the rule, which several subsystems implement independently:

- A page that could not be fetched is **not** a page without your brand on it.
- A response that was truncated is evidence of what *was* said, never of what
  was not.
- A citation that is a redirect wrapper tells you nothing about the publisher
  behind it.
- An empty model answer is **not** an observation that your brand was absent.

In every one of those cases the correct outcome is `check_failed` with
`confidence: 0.0`, **not** a gap. See `diagnosis/probe.py`,
`diagnosis/citations.py`, and `monitor/graph.py` for how this is enforced, and
`tests/test_citations.py` / `tests/test_truncation.py` for what it looks like
pinned down.

A corollary for passing checks: **a "no problem here" verdict must be as
auditable as a failing one.** `check_cited_domains` and the sitemap check record
the full basis of their conclusion — which documents were fetched, with what
status, how many URLs, how many matched — so a reader can re-derive the verdict
by hand. If you add a check, record its working.

## Getting set up

```bash
cp .env.example .env
docker compose up          # everything, in mock mode, no API keys, no cost
```

Or run the services on the host — see `docs/DEPLOYMENT.md`.

## Tests

```bash
cd services/pipeline && uv run pytest        # 328 tests; needs Postgres up
cd apps/api && npx tsc --noEmit && node --import tsx --test src/tests/*.test.ts
```

Most tests run offline in mock mode. Tests that need the database skip cleanly
if it is unreachable rather than failing, so a partial environment still gives
you a useful signal.

`tests/test_diagnosis_live.py` makes real network calls and is excluded from the
default run.

## Style

- **Python**: `ruff` and `black`, both run in CI. `uv run ruff check --fix app tests && uv run black app tests`.
- **TypeScript**: `prettier` and `eslint`; `tsc --noEmit` must be clean.
- Config over code. Engines, models, prices, thresholds and taxonomies live in
  `services/pipeline/config/*.yaml`. Adding an engine or changing a threshold
  should not be a code change.

## Comments

Explain **why**, especially when the code looks odd. Nearly every strange-looking
branch here is load-bearing and has a bug behind it — the entity resolver's
conservatism, the gateway's cache exclusion for `measurement`, the seed's
refusal to run in production. If you fix a real bug, leave a sentence saying
what it was. Future readers cannot infer it, and the tests that pin it read much
better with the reason attached.

## Adding an engine

A provider adapter is a file in `app/gateway/providers/` decorated with
`@register_provider("name")`, plus an entry in `config/models.yaml`. Nothing
else changes — no enum, no import list, no edit to the gateway.

**Grounding is mandatory for a measurement engine.** An ungrounded answer
measures training-data recall and returns no citations, which makes the whole
diagnosis layer inert. If an engine cannot ground, it does not ship.

If you add one, please also record in `docs/ENGINES.md`: how grounding is
billed, whether citations are publisher URLs or redirect wrappers, the free-tier
reality, and whether grounding conflicts with structured output — each with a
documentation link. And mark it honestly: if you have not made a live call, say
so at the top of the adapter, as the existing unverified adapters do.

## Adding a generator

Content generators are deliberately not part of this distribution. The interface
and registry are, and a generator plugs in with no fork — see
`docs/WRITING-A-GENERATOR.md`.

## What is out of scope

- **Content generation.** The `Generator` interface and registry are here; the
  concrete generators are not, and are unlikely to be accepted.
- **Dark mode.** Deliberately light-only; it doubles the UI surface for no
  adoption benefit.
- **A component library or design system** in `apps/web`. Default Tailwind,
  no dependencies. Consistency matters more than polish.

## Licence

AGPL-3.0-or-later. By contributing you agree your work is licensed under it.
New source files should carry the SPDX header the rest of the tree uses:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 <you>
```

Self-hosting and personal use carry no obligations. The copyleft obligation
applies only to offering a **modified** version as a network service.
