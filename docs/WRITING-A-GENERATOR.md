# Writing a generator

This distribution ships **zero content generators**. Planning ranks your gaps
and stops. Generators are the extension point — implement one and the same
pipeline starts producing assets, with no fork and no edit to this repository.

## The contract

```python
from app.pipeline.execution.base import Generator
from app.pipeline.execution.contracts import AssetDraft, GeneratorContext, PlanItem


class MyGenerator(Generator):
    fix_type = "add_llms_txt"      # matches what the planner emits for a gap_type
    asset_type = "llms_txt"        # the label recorded on the assets row

    def generate(self, item: PlanItem, context: GeneratorContext) -> AssetDraft:
        return AssetDraft(
            asset_type=self.asset_type,
            fix_type=self.fix_type,
            title=f"/llms.txt for {context.brand_name}",
            content="# " + context.brand_name,
            content_kind="text",          # "text" or "html"
            claims=[],                    # see "Claims" below
            target_prompt_ids=context.target_prompt_ids,
        )
```

`fix_type` values come from `config/gap_taxonomy.yaml` and are scored in
`config/planner.yaml`. A generator whose `fix_type` no gap produces is simply
never called.

## Registering it

Three ways, in the order the registry resolves them:

**1. Entry point** — for a separate installable package. This is the one to use
for a private or commercial generator set:

```toml
# in YOUR package's pyproject.toml
[project.entry-points."geo.generators"]
comparison_page = "mypkg.generators:ComparisonPageGenerator"
```

`pip install` it alongside the pipeline and it is discovered on import. The
value may be a `Generator` subclass or a factory; anything taking a single
argument is handed the `Gateway`.

**2. In-process** — for an application that composes this package directly:

```python
from app.pipeline.execution.registry import register_generator
register_generator(MyGenerator())
```

**3. Explicit injection** — for tests and for composing without global state:

```python
run_execution(account_id, scan_id=scan_id, registry={"add_llms_txt": MyGenerator()})
```

A plugin that fails to import is logged and skipped, never fatal: a broken
third-party generator must not take monitoring down.

## What the pipeline guarantees you

By the time `generate()` is called, the context has already been through
`facts_gate.sanitize_context`. **Placeholder facts are gone** — an unfilled
`"⚠️ your real starting price"` is not in `context.verified_facts`, so you
cannot publish one by forgetting to check. What was dropped is listed on
`context.dropped_placeholder_facts` so a refusal can name the rows still waiting
to be filled in.

## What you owe the pipeline

**Every claim about a real party must be backed by a verified fact.** Declare
them, and `validate.finalize_asset` checks each one:

```python
Claim(fact_type="pricing", key="starting_price", value="$9/mo", about="self")
```

- `about="self"` or `about="competitor"` → must match an active row in
  `verified_facts`, *with the same subject*. A fact about you cannot back a
  claim about a rival — that is how a customer's price gets published as a
  competitor's.
- `about="general"` → industry statements about nobody in particular, exempt.
- `claim.value` must equal the stored fact's display string exactly.

An asset with any violation is stored with `status="rejected"` and
`validation_state="failed"`. It is never marked deliverable. HTML is sanitized
with `nh3` regardless, and FAQPage JSON-LD is structurally validated.

## Refusing to generate

Sometimes the honest output is nothing. Raise `GenerationBlocked` with a reason
the customer can act on:

```python
from app.pipeline.execution.facts_gate import GenerationBlocked

raise GenerationBlocked(
    f"No verified facts about {competitor} — we can't build this comparison "
    f"until you provide facts about {competitor}.",
    {"missing": "competitor_facts", "competitor": competitor},
)
```

The runner records this as an outcome, not a crash, and the backlog travels with
it. **Prefer refusing over emitting something hollow.** An empty artifact that
passes validation is worse than no artifact: it looks like success.

That is a real lesson from this codebase. A generator once shipped a 119-byte
`/llms.txt` that named four competitors and said nothing about the customer. It
passed every check — because zero claims and all-claims-verified are
indistinguishable to a claim validator. If your generator can produce nothing
useful, say so instead.

## A worked example

`services/pipeline/examples/generators/robots_txt.py` is the smallest complete
generator: deterministic, no LLM, no claims. Read it first — it shows the whole
interface without a model call in the way. It is **not registered by default**;
wire it up with `register_generator(RobotsTxtFixer())` to see the mechanism run.

## Testing yours

Drive the stage directly with an explicit registry — no global state, no
network:

```python
out = generate_top_fix(gaps, context, registry={"add_llms_txt": MyGenerator()})
assert out.produced_asset
assert out.asset.validation_state == "passed"
```

`tests/test_no_generators.py` and `tests/test_placeholder_gate.py` show the
pattern, including how to assert that the placeholder gate protected a generator
that never thinks about placeholders at all.
