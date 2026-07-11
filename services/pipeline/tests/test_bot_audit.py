"""robots.txt bot audit: correct verdict + the GPTBot-allowed/SearchBot-blocked
trap, driven by a fixture robots.txt (no network)."""

from __future__ import annotations

from app.pipeline.diagnosis.fetcher import FakeFetcher, FetchResult
from app.pipeline.diagnosis.robots_audit import audit_robots

TARGET = "https://8.8.8.8/"  # public IP literal: passes SSRF, needs no DNS

ROBOTS = """
User-agent: OAI-SearchBot
Disallow: /

User-agent: Bingbot
Disallow: /

User-agent: GPTBot
Allow: /

User-agent: *
Disallow:
""".strip()


def _fetcher(robots_text: str | None) -> FakeFetcher:
    pages = {}
    if robots_text is not None:
        pages[f"{TARGET}robots.txt"] = FetchResult(
            url=f"{TARGET}robots.txt",
            final_url=f"{TARGET}robots.txt",
            status=200,
            ok=True,
            text=robots_text,
            content_type="text/plain",
        )
    return FakeFetcher(pages)


def test_blocked_search_bots_and_trap():
    audit, findings = audit_robots(_fetcher(ROBOTS), TARGET)

    assert audit.robots_found is True
    assert "OAI-SearchBot" in audit.blocked_search_bots
    assert "Bingbot" in audit.blocked_search_bots
    # GPTBot (training) allowed but OAI-SearchBot (search) blocked -> trap.
    assert "gptbot_allowed_searchbot_blocked" in audit.traps_triggered

    # Every blocked search bot is an urgent crawler gap.
    urgent = [f for f in findings if f.severity == "urgent" and not f.ok]
    assert any(f.gap_type == "blocked_crawler" for f in urgent)

    verdict = {v.name: v.allowed for v in audit.verdicts}
    assert verdict["GPTBot"] is True
    assert verdict["OAI-SearchBot"] is False
    assert verdict["Googlebot"] is True  # not mentioned -> allowed by default


def test_missing_robots_allows_all():
    audit, findings = audit_robots(_fetcher(None), TARGET)
    assert audit.robots_found is False
    assert audit.blocked_search_bots == []
    assert all(v.allowed for v in audit.verdicts)
