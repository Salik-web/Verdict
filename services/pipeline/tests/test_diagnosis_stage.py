"""Diagnosis stage end-to-end with a fake fetcher (no network) and the gateway in
mock mode: produces SEO + GEO findings, a bot-audit verdict, and typed Gaps."""

from __future__ import annotations

import uuid

from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.diagnosis.contracts import DiagnosisContext
from app.pipeline.diagnosis.fetcher import FakeFetcher, FetchResult
from app.pipeline.diagnosis.stage import diagnose

TARGET = "https://8.8.8.8/"

HOME_HTML = """
<html><head><title>Acme Analytics</title></head>
<body>
  <h1>Acme Analytics</h1>
  <p>We help B2B SaaS teams understand product usage with warehouse analytics.</p>
  <a href="/pricing">Pricing</a>
  <a href="/docs">Docs</a>
</body></html>
""".strip()

ROBOTS = "User-agent: OAI-SearchBot\nDisallow: /\n\nUser-agent: *\nDisallow:"


def _page(url: str, text: str, ok: bool = True) -> FetchResult:
    return FetchResult(
        url=url, final_url=url, status=200 if ok else 404, ok=ok, text=text
    )


def _fetcher() -> FakeFetcher:
    return FakeFetcher(
        {
            TARGET: _page(TARGET, HOME_HTML),
            f"{TARGET}robots.txt": _page(f"{TARGET}robots.txt", ROBOTS),
            # llms.txt intentionally absent -> 404 -> missing_llms_txt
        }
    )


def _gateway():
    return build_gateway(
        mode="mock", cost_sink=NullCostSink(), config=get_models_config()
    )


def _context() -> DiagnosisContext:
    return DiagnosisContext(
        account_id=uuid.uuid4(),
        scan_id=uuid.uuid4(),
        brand_name="Acme Analytics",
        brand_aliases=["Acme"],
        target_url=TARGET,
        competitor_urls=[],
    )


def test_diagnosis_produces_findings_gaps_and_bot_verdict():
    out = diagnose(_context(), _fetcher(), _gateway())

    assert out.findings, "expected SEO/GEO/crawler findings"
    gap_types = {g.gap_type for g in out.gaps}

    # SEO
    assert "missing_schema" in gap_types  # no JSON-LD in HOME_HTML
    # GEO
    assert "no_owned_comparison_page" in gap_types  # no vs/compare links
    assert "weak_page_structure" in gap_types  # mock geo_assessment -> not quotable
    # llms.txt
    assert "missing_llms_txt" in gap_types
    # crawler audit
    assert "blocked_crawler" in gap_types
    assert "OAI-SearchBot" in out.bot_audit.blocked_search_bots

    # Gaps carry a fix_type and a rank; highest-ranked first.
    blocked = next(g for g in out.gaps if g.gap_type == "blocked_crawler")
    assert blocked.fix_type == "fix_robots_txt"
    assert out.gaps == sorted(out.gaps, key=lambda g: -g.rank_score)
