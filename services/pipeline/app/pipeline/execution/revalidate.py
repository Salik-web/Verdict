# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Re-check stored assets against the CURRENT validator.

Audit finding #7. The comparison page from scan c1f854e5 is still recorded
`validation_state = passed` while containing the `@iga` JSON-LD defect the
validator now catches:

    mainEntity[3].acceptedAnswer.@type is not Answer: None
    mainEntity[3].acceptedAnswer.text is empty

It passed because it was generated before the validator existed. A passing record
on a broken artifact is worse than no record: it is the row someone trusts when
deciding to publish.

WHAT IS AND ISN'T RE-CHECKED — the distinction is deliberate:

  re-checked   JSON-LD structure, placeholder markers, script survival. These are
               properties OF THE ARTIFACT: the same bytes give the same verdict
               today, last week, and next year.
  not re-checked  claim-vs-verified-fact. That depends on the verified_facts table
               AS IT IS NOW, and facts get corrected, retired and re-worded. Re-
               running it would fail assets that were perfectly honest when they
               were written — replacing a false pass with a false fail. Those
               assets are marked `claims_rechecked: false` rather than guessed at.

An asset with no `validator_version` in its metadata predates validation
entirely; it is reported as UNVERIFIED so nothing is silently asserted about it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.pipeline.execution.contracts import AssetDraft, Claim
from app.pipeline.execution.facts_gate import placeholder_violations
from app.pipeline.execution.jsonld import validate_faqpage
from app.pipeline.execution.validate import VALIDATOR_VERSION

# Verdicts this reports. Deliberately NOT new values of the assets enum: the DB
# already has a `pending` state meaning "not established", and adding an enum
# value would need a migration to say something the existing one already says.
UNVERIFIED = "unverified"  # we could NOT re-check it (the artifact is unreadable)
STILL_VALID = "still_valid"  # re-checked against the current validator: clean
NOW_INVALID = "now_invalid"  # was recorded passing; the current validator rejects it


@dataclass
class Revalidation:
    asset_id: uuid.UUID
    title: str | None
    verdict: str
    stored_state: str
    violations: list[str] = field(default_factory=list)
    claims_rechecked: bool = False

    @property
    def needs_write(self) -> bool:
        # STILL_VALID is written too — the point of the exercise is that the record
        # says which validator established it, so "passed" stops being a claim
        # about an unknown vintage.
        return True


def _draft_from_metadata(asset_type, fix_type, title, content, metadata) -> AssetDraft:
    """Rebuild just enough of the draft for the artifact-level checks."""
    return AssetDraft(
        asset_type=asset_type or "unknown",
        fix_type=(metadata or {}).get("fix_type", "unknown"),
        title=title or "",
        content=content or "",
        content_kind=(metadata or {}).get("content_kind", "html"),
        schema_jsonld=(metadata or {}).get("schema_jsonld"),
        claims=[
            Claim.model_validate(c)
            for c in (metadata or {}).get("claims", [])
            if isinstance(c, dict)
        ],
    )


def revalidate(
    *,
    asset_id: uuid.UUID,
    asset_type: str | None,
    title: str | None,
    content: str,
    metadata: dict | None,
    validation_state: str,
    readable: bool = True,
) -> Revalidation:
    """Artifact-level re-check of one stored asset. Pure: no DB, no network."""
    metadata = metadata or {}
    draft = _draft_from_metadata(asset_type, None, title, content, metadata)

    if not readable:
        # We cannot open the artifact, so we cannot say anything about it. Saying
        # nothing is the point: an unverifiable record must not keep claiming to
        # have passed.
        return Revalidation(
            asset_id=asset_id,
            title=title,
            verdict=UNVERIFIED,
            stored_state=validation_state,
            violations=["artifact file is missing — could not re-check"],
        )

    violations = validate_faqpage(draft.schema_jsonld)
    violations += placeholder_violations(draft)
    if draft.content_kind == "html" and "<script" in (content or "").lower():
        violations.append("sanitization failed: a script tag survived")

    verdict = NOW_INVALID if violations else STILL_VALID

    return Revalidation(
        asset_id=asset_id,
        title=title,
        verdict=verdict,
        stored_state=validation_state,
        violations=violations,
        claims_rechecked=False,
    )


def revalidate_stored_assets(
    session, account_id: uuid.UUID | None = None, *, apply: bool = False
) -> list[Revalidation]:
    """Re-check every stored asset (optionally one account's).

    `apply=False` reports only — the caller decides. With `apply=True`, an asset
    the current validator rejects is flipped to failed/rejected and its
    violations are written into metadata, so the record stops asserting something
    untrue. Nothing is deleted: the artifact and its history stay intact.
    """
    from sqlalchemy import select

    from app.db.models import Asset
    from app.pipeline.execution.config import PIPELINE_ROOT

    stmt = select(Asset)
    if account_id is not None:
        stmt = stmt.where(Asset.account_id == account_id)

    results: list[Revalidation] = []
    for row in session.scalars(stmt).all():
        content, readable = "", False
        if row.content_ref:
            path = PIPELINE_ROOT / row.content_ref
            if path.is_file():
                content = path.read_text(encoding="utf-8")
                readable = True
        result = revalidate(
            asset_id=row.id,
            asset_type=row.type,
            title=row.title,
            content=content,
            metadata=dict(row.metadata_ or {}),
            validation_state=row.validation_state,
            readable=readable,
        )
        results.append(result)

        if not apply or not result.needs_write:
            continue
        metadata = dict(row.metadata_ or {})
        metadata["revalidation"] = {
            "at": datetime.now(UTC).isoformat(),
            "validator_version": VALIDATOR_VERSION,
            "verdict": result.verdict,
            "violations": result.violations,
            # Say plainly what was NOT re-checked, so nobody reads this as a
            # full re-validation.
            "claims_rechecked": False,
        }
        if result.verdict == NOW_INVALID:
            metadata["violations"] = result.violations
            row.validation_state = "failed"
            row.status = "rejected"
        elif result.verdict == UNVERIFIED and row.validation_state == "passed":
            # Can't open it, so can't stand behind it. `pending` is the schema's
            # existing "not established" state — no migration needed to say this.
            row.validation_state = "pending"
        else:
            # Re-checked and clean: record WHICH validator established that, so
            # "passed" stops being a claim of unknown vintage.
            metadata["validator_version"] = VALIDATOR_VERSION
        row.metadata_ = metadata
    return results
