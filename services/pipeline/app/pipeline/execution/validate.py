"""Output validation: enforce the verified-facts rule and sanitize HTML.

HARD RULE: every claim ABOUT SOMEONE — the customer ('self') or a named rival
('competitor') — MUST match an active verified fact. Unverified or mismatched,
the asset is rejected (flagged) and never marked deliverable. Stating a
competitor's pricing from the model's imagination is a factual and legal risk on
a customer's site, so it is checked exactly like a claim about the customer.

Only `general` claims (industry statements about nobody in particular) are exempt.

HTML is sanitized with nh3 (scripts and dangerous attributes stripped) as XSS
defense.
"""

from __future__ import annotations

import nh3

from app.pipeline.execution.contracts import (
    Asset,
    AssetDraft,
    Claim,
    GeneratorContext,
    VerifiedFactRef,
)
from app.pipeline.execution.jsonld import validate_faqpage

# Claims about a real party must be backed; `general` is not about anyone.
_MUST_BE_VERIFIED = ("self", "competitor")


def _describe(claim: Claim) -> str:
    """'competitor claim about Globex' / 'self claim' — so a violation names who."""
    if claim.about == "competitor":
        return "competitor claim"
    return f"{claim.about} claim"


def _lookup(context: GeneratorContext, claim: Claim) -> VerifiedFactRef | None:
    return context.fact(claim.fact_type, claim.key)


def _validate_claims(draft: AssetDraft, context: GeneratorContext) -> list[str]:
    violations: list[str] = []
    for claim in draft.claims:
        if claim.about not in _MUST_BE_VERIFIED:
            continue
        what = _describe(claim)
        fact = _lookup(context, claim)

        if fact is None:
            violations.append(
                f"unverified {what}: {claim.fact_type}/{claim.key} "
                "is not in verified_facts"
            )
            continue

        # A fact about the customer cannot back a claim about a rival (or vice
        # versa) — that would publish our price as theirs.
        if fact.about != claim.about:
            violations.append(
                f"wrong subject for {claim.fact_type}/{claim.key}: {what} backed by "
                f"a fact about '{fact.about}'"
            )
            continue

        if claim.value.strip() != fact.display.strip():
            violations.append(
                f"fact mismatch for {claim.fact_type}/{claim.key}: "
                f"claim '{claim.value}' != verified '{fact.display}'"
            )
    return violations


def finalize_asset(draft: AssetDraft, context: GeneratorContext) -> Asset:
    violations = _validate_claims(draft, context)

    # Malformed structured data is a silent SEO failure (a dropped FAQ entry, an
    # invalid rich result) — reject it here instead of shipping it.
    violations.extend(validate_faqpage(draft.schema_jsonld))

    if draft.content_kind == "html":
        content = nh3.clean(draft.content)
        if "<script" in content.lower():  # defense in depth
            violations.append("sanitization failed: a script tag survived")
    else:
        content = draft.content

    passed = not violations
    return Asset(
        asset_type=draft.asset_type,
        fix_type=draft.fix_type,
        title=draft.title,
        content=content,
        content_kind=draft.content_kind,
        schema_jsonld=draft.schema_jsonld,
        claims=draft.claims,
        target_prompt_ids=draft.target_prompt_ids,
        validation_state="passed" if passed else "failed",
        status="validated" if passed else "rejected",
        violations=violations,
    )
