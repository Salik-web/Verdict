"""Output validation: enforce the verified-facts rule and sanitize HTML.

HARD RULE: every 'self' (customer-specific) claim MUST match an active verified
fact. Any unverified or mismatched self claim fails validation and the asset is
rejected (flagged), never marked deliverable. HTML is sanitized with nh3 (scripts
and dangerous attributes stripped) as XSS defense.
"""

from __future__ import annotations

import nh3

from app.pipeline.execution.contracts import Asset, AssetDraft, GeneratorContext


def _validate_claims(draft: AssetDraft, context: GeneratorContext) -> list[str]:
    violations: list[str] = []
    for claim in draft.claims:
        if claim.about != "self":
            continue  # only customer-specific claims are fact-checked
        fact = context.fact(claim.fact_type, claim.key)
        if fact is None:
            violations.append(
                f"unverified self claim: {claim.fact_type}/{claim.key} "
                "is not in verified_facts"
            )
        elif claim.value.strip() != fact.display.strip():
            violations.append(
                f"fact mismatch for {claim.fact_type}/{claim.key}: "
                f"claim '{claim.value}' != verified '{fact.display}'"
            )
    return violations


def finalize_asset(draft: AssetDraft, context: GeneratorContext) -> Asset:
    violations = _validate_claims(draft, context)

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
