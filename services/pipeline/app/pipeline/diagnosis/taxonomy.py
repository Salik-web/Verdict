# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Map findings to typed Gaps via config/gap_taxonomy.yaml.

A failing finding with a gap_type becomes a Gap: fix_type + layer come from the
taxonomy, rank_score = base_rank x severity weight x detection confidence.

Several DIFFERENT checks can land on the same gap_type — e.g. `weak_headings`
(the page has no H1) and `not_quotable` (the LLM judge found the prose
unquotable) both mean `weak_page_structure`. They are merged into ONE gap
carrying both reasons: a customer should read "your page structure is weak, for
these two reasons", not two separate gaps that imply two separate problems.
"""

from __future__ import annotations

from app.pipeline.diagnosis.config import get_gap_taxonomy
from app.pipeline.diagnosis.contracts import Finding, Gap


def finding_to_gap(finding: Finding) -> Gap | None:
    if finding.ok or not finding.gap_type:
        return None
    # ONLY a confirmed absence may become a gap. A check that failed (403, 429,
    # timeout) knows nothing, and telling a customer "you don't have X" because
    # their WAF refused us is the bug this guard exists to prevent.
    if finding.status != "confirmed_absent":
        return None
    tax = get_gap_taxonomy()
    gdef = tax.gaps.get(finding.gap_type)
    if gdef is None:
        return None  # unknown gap_type: not in the taxonomy, skip
    weight = tax.severity_weights.get(finding.severity, 0.5)
    # Detection confidence scales the stored rank AND is carried in details so the
    # planner can refuse to rank a weak inference at all.
    return Gap(
        gap_type=finding.gap_type,
        fix_type=gdef.fix_type,
        layer=gdef.layer,
        severity=finding.severity,
        rank_score=round(gdef.base_rank * weight * finding.confidence, 4),
        summary=finding.summary,
        details={
            **finding.detail,
            "finding_code": finding.code,
            "detection_confidence": finding.confidence,
            # The audit trail: what we fetched to justify this gap.
            "evidence": [e.model_dump() for e in finding.evidence],
        },
    )


def _reason(finding: Finding) -> dict:
    """One supporting reason, kept verbatim so a merged gap loses nothing."""
    return {
        "finding_code": finding.code,
        "layer": finding.layer,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "summary": finding.summary,
        "detail": finding.detail,
    }


def _merge(pairs: list[tuple[Finding, Gap]]) -> Gap:
    """Collapse same-gap_type findings into one Gap, preserving every reason.

    The strongest finding (highest rank = severity x confidence) leads: it sets
    the summary, severity and score, since acting on the gap is justified by its
    best evidence. The others survive as `details.reasons`.
    """
    ordered = sorted(pairs, key=lambda p: -p[1].rank_score)
    primary_finding, primary_gap = ordered[0]
    if len(ordered) == 1:
        primary_gap.details["reasons"] = [_reason(primary_finding)]
        return primary_gap

    # Union the evidence, first occurrence wins, so the trail covers every URL
    # any of the merged checks actually fetched.
    evidence: list[dict] = []
    seen: set[tuple] = set()
    for finding, _ in ordered:
        for e in finding.evidence:
            key = (e.url, e.status)
            if key not in seen:
                seen.add(key)
                evidence.append(e.model_dump())

    merged_detail: dict = {}
    for _, gap in reversed(ordered):  # primary's keys win on conflict
        merged_detail.update(
            {
                k: v
                for k, v in gap.details.items()
                if k not in ("evidence", "reasons", "finding_code")
            }
        )

    primary_gap.details = {
        **merged_detail,
        "finding_code": primary_finding.code,
        # Highest confidence: the gap is justified by its strongest evidence.
        "detection_confidence": max(f.confidence for f, _ in ordered),
        "evidence": evidence,
        "reasons": [_reason(f) for f, _ in ordered],
        "merged_from": [f.code for f, _ in ordered],
    }
    return primary_gap


def findings_to_gaps(findings: list[Finding]) -> list[Gap]:
    pairs = [(f, g) for f in findings if (g := finding_to_gap(f)) is not None]

    by_type: dict[str, list[tuple[Finding, Gap]]] = {}
    for finding, gap in pairs:
        by_type.setdefault(gap.gap_type, []).append((finding, gap))

    gaps = [_merge(group) for group in by_type.values()]
    gaps.sort(key=lambda g: -g.rank_score)
    return gaps
