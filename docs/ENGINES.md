# Engines

Four measurement engines ship. You need a key for **at most one** — an engine
whose key is missing is reported unavailable and skipped, so a single key gives
you a working single-engine scan. With no keys at all, `GATEWAY_MODE=mock` runs
the entire pipeline against fixtures for free.

## Verification status — read this first

Only Gemini has ever made a live call from this codebase. The other three were
implemented against published documentation and are covered by unit tests using
recorded response *shapes*. They are wired, priced, and gated, but the first
real scan is their acceptance test.

| Engine | Adapter | Status |
| --- | --- | --- |
| **Gemini** 2.5 Flash | `providers/gemini.py` | **Verified live.** Used for every real scan during development. |
| **Perplexity** Sonar | `providers/openai_compatible.py` | **Unverified.** The adapter has run live (OpenRouter), its Perplexity grounded-source path has not. |
| **OpenAI** GPT-4.1 | `providers/openai_responses.py` | **Unverified.** Never made a live call. |
| **Claude** | `providers/anthropic.py` | **Unverified.** Never made a live call. |

Each unverified adapter carries the same warning at the top of its own file, so
the caveat is visible where the code is read, not only here.

## Grounding is mandatory

Every engine here is configured **grounded** — the model searches the live web
before answering. This is not a preference:

- an **ungrounded** answer is training-data recall. It tells you what the model
  absorbed months ago, not what a user asking today would see;
- an ungrounded answer **cites nothing**, and the entire diagnosis layer is
  driven by cited URLs.

An engine that cannot ground does not ship. That is why grounded OpenAI uses the
Responses API (`provider: openai_responses`) rather than `/chat/completions` —
grounding there is a different *endpoint*, not a flag.

## Cost per scan

A scan costs **(active prompts × repeats × engines)** grounded calls. Defaults
are `repeats: 5` (`config/monitor.yaml`), so **2 prompts = 10 grounded calls per
engine**. The table below is per scan at that size, retrieval fees only; token
costs are on top and are small by comparison.

| Engine | Grounding billed as | Per grounded call | 10-call scan | Free tier |
| --- | --- | --- | --- | --- |
| Gemini 2.5 Flash | per grounded **prompt** | $0.035 | **$0.35** | **1,500 grounded req/day free**, but the *model* is capped at ~20 req/day/project on the free tier ⇒ **~2 scans/day** |
| Perplexity Sonar | per **request**, by context size | $0.005 / $0.008 / $0.012 (low/med/high) | **$0.05 – $0.12** | **None.** Tier 0 has no monthly credits; $50 cumulative spend to reach Tier 1 |
| OpenAI (Responses) | per **tool call** | $0.010 | **$0.10** | None |
| Claude (Messages) | per **search** | $0.010 | **$0.10+** | None |

> **Claude and OpenAI bill per *search*, not per request**, and one request can
> run several. `max_searches` (Claude's `max_uses`) caps it — the dev profile
> sets 3, so a 10-call scan is *up to* $0.30, not $0.10. The adapters report the
> real count back and the ledger prices it per search; see `grounded_units`.

### The tradeoff, plainly

- **Gemini for free evaluation.** It is the only engine with a genuinely free
  path, and it is the only one verified live. The free-tier ceiling of ~20
  requests/day/model works out to about **two scans a day** at default settings
  — enough to try the product, not enough to run it.
- **Perplexity for serious use.** At $0.005–$0.012 per grounded request it is
  **3–7× cheaper than Gemini**, and cheaper than OpenAI or Claude. The catch is
  that there is **no free tier at all**: you must buy $50 of credit before the
  rate limits are usable.

So: evaluate on Gemini, run on Perplexity. Add OpenAI or Claude when you
specifically care what *those* assistants say about you — they are the same
price as each other and roughly 2× Perplexity.

## Citations

The diagnosis layer reads cited URLs, so their shape decides how much it can
conclude (see `app/pipeline/diagnosis/citations.py`).

| Engine | Citation URLs | Publisher titles |
| --- | --- | --- |
| Gemini | **Redirect wrappers** — `vertexaisearch.cloud.google.com/grounding-api-redirect/…`. Verified. | Sometimes |
| Perplexity | **Unconfirmed.** `search_results[].url` documented, redirect behaviour not stated | Yes — `search_results[].title` |
| OpenAI | Direct publisher URLs, from `url_citation` annotations. Unverified. | Yes |
| Claude | **Direct publisher URLs** per the documented example. Unverified. | Yes |

Redirect wrappers are why domain-level checks never fetch, and why the
body-presence check reports `check_failed` rather than a gap when every URL is a
wrapper. A wrapper tells you nothing about the publisher behind it, so it cannot
support "your brand is absent from that page".

## Grounding vs structured output

**Gemini 2.5 cannot combine grounding with JSON mode.** The combination is
Gemini-3-only and in preview
([structured output docs](https://ai.google.dev/gemini-api/docs/structured-output)).
This is why `measurement` sets `grounding: true` and `json_output: false`, while
the parsing task (`processing`) is the reverse. Measurement answers must stay
prose anyway — that is what a user actually sees.

For Perplexity, OpenAI and Claude the constraint has **not been verified here**.
The pipeline does not ask any measurement engine for JSON, so it does not
currently matter; it would if you added a grounded task that needs structured
output.

## Enabling an engine

1. Put the key in `.env` (`PERPLEXITY_API_KEY`, `OPENAI_API_KEY`,
   `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`).
2. Uncomment its entry in `config/monitor.yaml`.
3. Restart the worker — config is read at import.

Leaving an engine enabled without a key costs nothing: it is skipped, with the
missing variable named. Check what a deployment can actually reach:

```python
from app.gateway.availability import all_task_statuses
for s in all_task_statuses("dev"):
    print(s.task, s.label, s.available, s.reason)
```

Every enabled engine **multiplies** your per-scan cost — four engines is four
times the grounded calls.

## Sources

- Gemini pricing — <https://ai.google.dev/gemini-api/docs/pricing>
- Perplexity pricing — <https://docs.perplexity.ai/getting-started/pricing>
- Perplexity tiers — <https://docs.perplexity.ai/guides/usage-tiers>
- Perplexity response shape — <https://docs.perplexity.ai/api-reference/chat-completions-post>
- OpenAI pricing — <https://developers.openai.com/api/docs/pricing>
- Claude web search — <https://platform.claude.com/docs/en/docs/agents-and-tools/tool-use/web-search-tool>

Prices checked 2026-08-16. They move; treat `config/models.yaml` as the source
of truth for what this install bills, and re-check before quoting these numbers.
