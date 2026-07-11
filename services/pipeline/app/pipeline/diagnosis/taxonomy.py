"""Map findings to typed Gaps via config/gap_taxonomy.yaml.

A failing finding with a gap_type becomes a Gap: fix_type + layer come from the
taxonomy, rank_score = base_rank x severity weight.
"""

from __future__ import annotations

from app.pipeline.diagnosis.config import get_gap_taxonomy
from app.pipeline.diagnosis.contracts import Finding, Gap


def finding_to_gap(finding: Finding) -> Gap | None:
    if finding.ok or not finding.gap_type:
        return None
    tax = get_gap_taxonomy()
    gdef = tax.gaps.get(finding.gap_type)
    if gdef is None:
        return None  # unknown gap_type: not in the taxonomy, skip
    weight = tax.severity_weights.get(finding.severity, 0.5)
    return Gap(
        gap_type=finding.gap_type,
        fix_type=gdef.fix_type,
        layer=gdef.layer,
        severity=finding.severity,
        rank_score=round(gdef.base_rank * weight, 4),
        summary=finding.summary,
        details={**finding.detail, "finding_code": finding.code},
    )


def findings_to_gaps(findings: list[Finding]) -> list[Gap]:
    gaps = [g for f in findings if (g := finding_to_gap(f)) is not None]
    gaps.sort(key=lambda g: -g.rank_score)
    return gaps
