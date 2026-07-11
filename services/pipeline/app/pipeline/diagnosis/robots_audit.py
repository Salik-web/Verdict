"""robots.txt crawler audit.

Fetches robots.txt and, for every AI bot in config/ai_bots.yaml, decides whether
it may fetch '/'. A blocked SEARCH bot (citation-time) is URGENT. A named trap
(training bot allowed while its paired search bot is blocked) is URGENT. Blocked
TRAINING bots are informational (often a deliberate choice).
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from app.pipeline.diagnosis.config import get_bot_registry
from app.pipeline.diagnosis.contracts import BotAudit, BotVerdict, Finding
from app.pipeline.diagnosis.fetcher import Fetcher


def robots_url_for(target_url: str) -> str:
    p = urlparse(target_url)
    return urlunparse((p.scheme, p.netloc, "/robots.txt", "", "", ""))


def _parser_for(robots_text: str) -> RobotFileParser:
    rp = RobotFileParser()
    rp.parse(robots_text.splitlines())
    return rp


def audit_robots(fetcher: Fetcher, target_url: str) -> tuple[BotAudit, list[Finding]]:
    registry = get_bot_registry()
    result = fetcher.get(robots_url_for(target_url))
    robots_found = result.ok and bool(result.text.strip())
    findings: list[Finding] = []

    # No robots.txt => nothing is disallowed; every bot may crawl.
    rp = _parser_for(result.text) if robots_found else None

    def allowed(token: str) -> bool:
        return True if rp is None else rp.can_fetch(token, "/")

    verdicts: list[BotVerdict] = []
    allow_by_name: dict[str, bool] = {}
    blocked_search: list[str] = []

    for bot in registry.bots:
        is_allowed = allowed(bot.token)
        allow_by_name[bot.name] = is_allowed
        verdicts.append(
            BotVerdict(name=bot.name, category=bot.category, allowed=is_allowed)
        )
        if not is_allowed and bot.category == "search":
            blocked_search.append(bot.name)
            findings.append(
                Finding(
                    layer="crawler",
                    code=f"blocked_search_bot:{bot.name}",
                    ok=False,
                    severity="urgent",
                    summary=f"{bot.name} (search) is blocked by robots.txt — "
                    f"{bot.vendor or 'this engine'} can't cite you.",
                    gap_type="blocked_crawler",
                    detail={"bot": bot.name, "category": "search"},
                )
            )
        elif not is_allowed and bot.category == "training":
            findings.append(
                Finding(
                    layer="crawler",
                    code=f"blocked_training_bot:{bot.name}",
                    ok=True,  # a choice, not a defect
                    severity="info",
                    summary=f"{bot.name} (training) is blocked — informational.",
                    detail={"bot": bot.name, "category": "training"},
                )
            )

    traps_triggered: list[str] = []
    for trap in registry.traps:
        if allow_by_name.get(trap.training) and not allow_by_name.get(
            trap.search, True
        ):
            traps_triggered.append(trap.name)
            findings.append(
                Finding(
                    layer="crawler",
                    code=f"trap:{trap.name}",
                    ok=False,
                    severity="urgent",
                    summary=trap.message,
                    gap_type="blocked_crawler",
                    detail={"trap": trap.name},
                )
            )

    if not robots_found:
        findings.append(
            Finding(
                layer="crawler",
                code="robots_txt_missing",
                ok=True,
                severity="info",
                summary="No robots.txt found — all crawlers allowed by default.",
            )
        )

    audit = BotAudit(
        robots_found=robots_found,
        verdicts=verdicts,
        blocked_search_bots=blocked_search,
        traps_triggered=traps_triggered,
    )
    return audit, findings
