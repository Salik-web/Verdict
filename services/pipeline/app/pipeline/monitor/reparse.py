"""Re-parse a completed scan's STORED answers — no new grounded calls.

Grounded measurement (Gemini) is the expensive, quota'd part; its verbatim output
is saved in mentions.raw_response_ref precisely so the parser can be fixed and
re-run for free. This re-runs only the 'processing' task (the cheap parser) over
those stored answers, applies the membership guard, and rewrites this scan's
mentions + share_of_voice rows in place. Measurement is never called.

Use after changing the extraction prompt or the guard, to repair a scan whose
competitors were fabricated by the old parser:

    python -m app.pipeline.monitor.reparse <scan_id>
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import Mention, ShareOfVoice
from app.db.repositories import MentionRepository, ShareOfVoiceRepository
from app.gateway import Gateway, get_gateway
from app.pipeline.contracts import CitationSource
from app.pipeline.monitor.parse import parse_answer
from app.pipeline.monitor.records import records_for_answer
from app.pipeline.monitor.runner import load_scan_context
from app.pipeline.monitor.sov import compute_sov, make_brand_resolver


def reparse_scan(
    scan_id: uuid.UUID | str,
    account_id: uuid.UUID | str | None = None,
    gateway: Gateway | None = None,
) -> dict[str, Any]:
    scan_id = _as_uuid(scan_id)
    # Resolve the gateway here (not at param default) so the re-parse uses the
    # configured 'processing' provider — measurement/grounded is never called.
    gateway = gateway or get_gateway()

    with SessionLocal() as session:
        if account_id is None:
            account_id = session.scalars(
                select(Mention.account_id).where(Mention.scan_id == scan_id).limit(1)
            ).first()
            if account_id is None:
                raise ValueError(f"no mentions found for scan {scan_id}")
        account_id = _as_uuid(account_id)

        context = load_scan_context(session, account_id, scan_id)

        # The stored answers live on the target rows (one per prompt/engine/run):
        # they carry raw_response_ref + cited_urls. Competitor rows carry neither,
        # so they're rebuilt from the re-parse, not read.
        target_rows = session.scalars(
            select(Mention).where(
                Mention.scan_id == scan_id,
                Mention.brand == context.brand_name,
                Mention.raw_response_ref.is_not(None),
            )
        ).all()
        answers = [
            (
                r.prompt_id,
                r.engine,
                r.run,
                r.raw_response_ref,
                [CitationSource(**c) for c in (r.cited_urls or [])],
            )
            for r in target_rows
        ]

    if not answers:
        raise ValueError(
            f"scan {scan_id} has no stored raw answers to re-parse "
            "(only scans run after the raw_response fix can be re-parsed)"
        )

    resolve = make_brand_resolver(context)
    focal_competitor_id, _ = resolve(context.brand_name)

    mentions = []
    parses = []
    for prompt_id, engine, run, raw_text, cited in answers:
        parsed = parse_answer(gateway, context, answer_text=raw_text, scenario=None)
        parses.append((engine, parsed))
        mentions.extend(
            records_for_answer(
                prompt_id=prompt_id,
                engine=engine,
                run=run,
                brand_name=context.brand_name,
                focal_competitor_id=focal_competitor_id,
                parsed=parsed,
                cited=cited,
                raw_response=raw_text,
                resolve=resolve,
            )
        )

    share_of_voice = compute_sov(context, parses)

    with SessionLocal() as session:
        # Replace this scan's derived rows; the stored raw answers are untouched.
        session.execute(delete(ShareOfVoice).where(ShareOfVoice.scan_id == scan_id))
        session.execute(delete(Mention).where(Mention.scan_id == scan_id))
        n_mentions = MentionRepository(session).bulk_insert(
            account_id, scan_id, mentions
        )
        n_sov = ShareOfVoiceRepository(session).insert_many(
            account_id, scan_id, share_of_voice
        )
        session.commit()

    return {
        "scan_id": str(scan_id),
        "answers_reparsed": len(answers),
        "mentions": n_mentions,
        "sov_rows": n_sov,
    }


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m app.pipeline.monitor.reparse <scan_id>")
        raise SystemExit(1)
    print(json.dumps(reparse_scan(sys.argv[1]), indent=2))
