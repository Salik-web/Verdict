# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Salik Syed
"""Re-check stored records against the current logic.

    # report only (default) — nothing is written
    python -m app.pipeline.execution.revalidate_cli
    # write the corrections back
    python -m app.pipeline.execution.revalidate_cli --apply
    # one account, or one kind of record
    python -m app.pipeline.execution.revalidate_cli --account <uuid> --what gaps

Two kinds of stale record, both of which keep asserting something the current
code would no longer conclude:

  assets  an artifact recorded `passed` that today's validator rejects (the
          `@iga` JSON-LD defect), or one we can no longer open.
  gaps    a finding raised by logic that has since been replaced — the
          homepage-anchors-only `no_owned_comparison_page`.

Report-only by default: flipping a stored record is a correction to history, and
whoever runs it should see what it will change first. The gap pass FETCHES THE
LIVE SITE to re-derive each verdict, so it is also a network operation.
"""

from __future__ import annotations

import argparse
import uuid

from app.db.base import SessionLocal
from app.pipeline.diagnosis.revalidate import (
    INCONCLUSIVE,
    NO_LONGER_RAISED,
    NOT_RECHECKABLE,
    STILL_RAISED,
    revalidate_stored_gaps,
)
from app.pipeline.execution.revalidate import (
    NOW_INVALID,
    STILL_VALID,
    UNVERIFIED,
    revalidate_stored_assets,
)


def _report_assets(session, account_id, apply: bool) -> None:
    results = revalidate_stored_assets(session, account_id, apply=apply)
    order = {NOW_INVALID: 0, UNVERIFIED: 1, STILL_VALID: 2}
    print("── assets " + "─" * 70)
    for r in sorted(results, key=lambda r: (order.get(r.verdict, 9), str(r.asset_id))):
        print(f"{r.verdict:12} stored={r.stored_state:8} {r.asset_id}  {r.title or ''}")
        for v in r.violations:
            print(f"             - {v}")
    counts = {k: sum(1 for r in results if r.verdict == k) for k in order}
    print(
        f"\n{len(results)} assets: {counts[NOW_INVALID]} now invalid, "
        f"{counts[UNVERIFIED]} unverified (artifact unreadable), "
        f"{counts[STILL_VALID]} still valid."
    )
    # Claim-vs-fact is state-dependent and deliberately not re-run; say so rather
    # than let this read as a full re-validation.
    print("Claims were NOT re-checked against verified_facts (see revalidate.py).")


def _report_gaps(session, account_id, apply: bool) -> None:
    results = revalidate_stored_gaps(session, account_id, apply=apply)
    order = {NO_LONGER_RAISED: 0, STILL_RAISED: 1, INCONCLUSIVE: 2, NOT_RECHECKABLE: 3}
    print("\n── gaps " + "─" * 72)
    for r in sorted(results, key=lambda r: (order.get(r.verdict, 9), str(r.gap_id))):
        rank = f"{r.rank_score:.3f}" if r.rank_score is not None else "-"
        print(
            f"{r.verdict:17} {r.gap_type:26} rank={rank:>6} "
            f"stored={r.stored_status:9} scan={r.scan_id}"
        )
        print(f"                  {r.reason}")
    counts = {k: sum(1 for r in results if r.verdict == k) for k in order}
    print(
        f"\n{len(results)} re-checkable gaps: {counts[NO_LONGER_RAISED]} no longer "
        f"raised, {counts[STILL_RAISED]} still raised, "
        f"{counts[INCONCLUSIVE]} inconclusive."
    )
    if counts[INCONCLUSIVE]:
        # The asymmetry is deliberate and worth stating out loud.
        print(
            "Inconclusive gaps were LEFT OPEN — a re-check we couldn't complete is "
            "not evidence the finding was wrong."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", type=uuid.UUID, default=None)
    parser.add_argument(
        "--what",
        choices=("assets", "gaps", "all"),
        default="all",
        help="which stored records to re-check (default: all)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write corrections back (default: report only)",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.what in ("assets", "all"):
            _report_assets(session, args.account, args.apply)
        if args.what in ("gaps", "all"):
            _report_gaps(session, args.account, args.apply)
        if args.apply:
            session.commit()

    if not args.apply:
        print("\nNothing was written. Re-run with --apply to correct the records.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
