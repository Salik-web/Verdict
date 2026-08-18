# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""One fetch -> (result, evidence, verdict) — the single place that decides what
an HTTP outcome actually PROVES.

Before this existed, every non-2xx collapsed into "absent": a 403 from a WAF, a
429 from rate limiting and a real 404 were indistinguishable, so a blocked crawl
produced confident findings about a site we never read. The rules:

  2xx            -> present            (definitive)
  404 / 410      -> absent             (definitive: the server says it isn't there)
  403 / 429 / 5xx-> check failed       (we were refused; we learned nothing)
  transport error-> check failed       (timeout / DNS / connection reset)

Every branch returns Evidence, so the verdict is auditable after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.pipeline.diagnosis.contracts import Evidence, Finding
from app.pipeline.diagnosis.fetcher import Fetcher, FetchResult

# Statuses that definitively mean "this resource does not exist".
_ABSENT_STATUSES = {404, 410}


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Probe:
    """Outcome of a single URL fetch."""

    url: str
    result: FetchResult | None
    evidence: Evidence

    @property
    def failed(self) -> bool:
        """True when we could not determine presence or absence."""
        if self.result is None:
            return True
        return not self.result.ok and self.result.status not in _ABSENT_STATUSES

    @property
    def present(self) -> bool:
        return self.result is not None and self.result.ok

    @property
    def absent(self) -> bool:
        return self.result is not None and self.result.status in _ABSENT_STATUSES


def probe(fetcher: Fetcher, url: str) -> Probe:
    """Fetch a URL, never raising: transport failures become CHECK_FAILED."""
    try:
        result = fetcher.get(url)
    except Exception as exc:  # FetchError, SSRFError, anything the client raises
        # Deliberately broad: any failure to reach the URL is the same epistemic
        # state (we don't know), and it must not abort the whole diagnosis.
        return Probe(
            url=url,
            result=None,
            evidence=Evidence(
                url=url,
                status=None,
                bytes=0,
                fetched_at=_now(),
                note=f"{type(exc).__name__}: {exc}"[:300],
            ),
        )
    analysed = len((result.text or "").encode("utf-8", "ignore"))
    return Probe(
        url=url,
        result=result,
        evidence=Evidence(
            url=url,
            status=result.status,
            final_url=result.final_url,
            bytes=analysed,
            fetched_at=_now(),
            truncated=result.truncated,
            content_bytes=result.content_bytes or analysed,
            note=(
                f"response clipped at the scraper cap: analysed {analysed} of "
                f"{result.content_bytes} bytes"
                if result.truncated
                else None
            ),
        ),
    )


def downgrade_truncated_absences(findings: list[Finding]) -> list[Finding]:
    """Turn "we didn't find it" into "we couldn't finish looking" when the page
    we searched was clipped.

    Applied once, over every finding, at the end of the checks — so a check added
    later inherits the rule instead of having to remember it. Only absence-based
    verdicts are touched: a noindex tag we actually read stays confirmed however
    much of the page went unread. Since the taxonomy only promotes
    `confirmed_absent` to a Gap, this is also what stops the gap being raised.
    """
    out: list[Finding] = []
    for finding in findings:
        clipped = [e for e in finding.evidence if e.truncated]
        if (
            finding.ok
            or finding.status != "confirmed_absent"
            or not finding.from_absence
            or not clipped
        ):
            out.append(finding)
            continue
        ev = clipped[0]
        out.append(
            finding.model_copy(
                update={
                    "status": "check_failed",
                    "confidence": 0.0,
                    "summary": (
                        f"{finding.summary} INCONCLUSIVE: only {ev.bytes} of "
                        f"{ev.content_bytes} bytes were analysed, so this absence "
                        "is not established."
                    ),
                    "detail": {
                        **finding.detail,
                        "truncated": True,
                        "analysed_bytes": ev.bytes,
                        "content_bytes": ev.content_bytes,
                    },
                }
            )
        )
    return out
