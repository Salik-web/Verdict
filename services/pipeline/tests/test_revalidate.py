# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Stored assets are re-checkable against the current validator.

Audit finding #7. The comparison page from scan c1f854e5 was recorded
`validation_state = passed` while carrying the `@iga` JSON-LD defect — the answer
landed under a misspelled key, so the FAQ entry had no answer at all. It passed
because it was generated before the validator existed, and a passing record on a
broken artifact is the row someone trusts when they decide to publish.

Re-running it here reproduces the audit's two violations exactly.
"""

from __future__ import annotations

import uuid

from app.pipeline.execution.revalidate import (
    NOW_INVALID,
    STILL_VALID,
    UNVERIFIED,
    revalidate,
)
from app.pipeline.execution.validate import VALIDATOR_VERSION

# The stored schema_jsonld of asset 8c73a9c6, abridged to the entry that matters.
IGA_JSONLD = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    "mainEntity": [
        {
            "@type": "Question",
            "name": "What is it?",
            "acceptedAnswer": {"@type": "Answer", "text": "A tool."},
        },
        {
            "@type": "Question",
            "name": "How much?",
            # The bug: the answer object is present but empty, because the model
            # wrote the text under "@iga".
            "acceptedAnswer": {"@iga": "It is $9/mo."},
        },
    ],
}

GOOD_JSONLD = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    "mainEntity": [
        {
            "@type": "Question",
            "name": "What is it?",
            "acceptedAnswer": {"@type": "Answer", "text": "A tool."},
        }
    ],
}


def _check(**over):
    base = dict(
        asset_id=uuid.uuid4(),
        asset_type="comparison_page",
        title="Acme vs Globex",
        content="<h1>Acme vs Globex</h1>",
        metadata={"content_kind": "html", "schema_jsonld": GOOD_JSONLD},
        validation_state="passed",
    )
    base.update(over)
    return revalidate(**base)


def test_the_grandfathered_iga_asset_is_caught():
    result = _check(metadata={"content_kind": "html", "schema_jsonld": IGA_JSONLD})
    assert result.verdict == NOW_INVALID
    assert result.violations == [
        "mainEntity[1].acceptedAnswer.@type is not Answer: None",
        "mainEntity[1].acceptedAnswer.text is empty",
    ]


def test_a_clean_asset_stays_valid():
    result = _check()
    assert result.verdict == STILL_VALID
    assert result.violations == []


def test_a_stored_placeholder_asset_is_caught():
    """The other half of finding #1: an llms.txt that shipped ⚠️ placeholders."""
    result = _check(
        asset_type="llms_txt",
        metadata={
            "content_kind": "text",
            "claims": [
                {
                    "fact_type": "pricing",
                    "key": "starting_price",
                    "value": "⚠️ ImagineArt's real starting price",
                    "about": "self",
                }
            ],
        },
        content="# ImagineArt\n- pricing/starting_price: ⚠️ real price",
    )
    assert result.verdict == NOW_INVALID
    assert any("placeholder" in v for v in result.violations)


def test_an_unreadable_artifact_is_unverified_not_passed():
    """We cannot open it, so we cannot stand behind it — and it must not keep
    claiming to have passed."""
    result = _check(readable=False)
    assert result.verdict == UNVERIFIED
    assert result.violations == ["artifact file is missing — could not re-check"]


def test_claims_are_never_silently_rechecked():
    """claim-vs-fact depends on verified_facts AS IT IS NOW; re-running it would
    fail assets that were honest when written. The flag says so out loud."""
    assert _check().claims_rechecked is False


def test_a_surviving_script_tag_is_caught():
    result = _check(content="<p>hi</p><script>alert(1)</script>")
    assert result.verdict == NOW_INVALID
    assert "sanitization failed" in result.violations[0]


def test_new_assets_record_which_validator_checked_them():
    """Without this stamp a stored `passed` is a claim of unknown vintage, and
    re-validation cannot tell a checked asset from a grandfathered one."""
    from app.pipeline.execution.contracts import Asset
    from app.pipeline.execution.runner import asset_metadata

    asset = Asset(
        asset_type="llms_txt",
        fix_type="add_llms_txt",
        title="t",
        content="x",
        content_kind="text",
        schema_jsonld=None,
        claims=[],
        target_prompt_ids=[],
        validation_state="passed",
        status="validated",
        violations=[],
    )
    assert asset_metadata(asset, 0.5)["validator_version"] == VALIDATOR_VERSION


def test_a_reused_asset_round_trips_through_revalidation():
    """Metadata written by the runner must be readable by the re-validator —
    otherwise every freshly generated asset re-reports as broken."""
    from app.pipeline.execution.contracts import Asset
    from app.pipeline.execution.runner import asset_metadata

    asset = Asset(
        asset_type="comparison_page",
        fix_type="generate_comparison_page",
        title="Acme vs Globex",
        content="<h1>Acme vs Globex</h1>",
        content_kind="html",
        schema_jsonld=GOOD_JSONLD,
        claims=[],
        target_prompt_ids=[],
        validation_state="passed",
        status="validated",
        violations=[],
    )
    result = _check(metadata=asset_metadata(asset, 0.9), content=asset.content)
    assert result.verdict == STILL_VALID
