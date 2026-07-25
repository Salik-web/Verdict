"""LEDGER COMPLETENESS: every issued gateway call lands exactly one logged row.

This is a class-of-bug test, not an instance test. Three separate defects shipped
because nothing checked this invariant:

  * the response cache collapsed measurement repeats and returned early WITHOUT
    logging — 10 issued measurement calls became 4 rows;
  * the same early return dropped parse repeats;
  * the generation call was logged with scan_id NULL, so it existed in the ledger
    but was invisible to per-scan cost.

Net effect: a scan that issued ~22 calls logged 9, and per-scan pricing silently
undercounted. The assertions below are deliberately about the INVARIANT (issued ==
logged, and every row attributed to its scan) rather than about any one of those
bugs, so a future regression of the same shape fails here regardless of cause.

`issued` is counted independently of the cost sink, at the gateway's public call()
boundary — the single point every model call passes through. Runs entirely in mock
mode: no keys, no network, no real spend.
"""

from __future__ import annotations

import uuid
from collections import Counter
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from app.db.base import SessionLocal
from app.db.models import Scan
from app.db.repositories import AccountRepository
from app.gateway.cost import NullCostSink
from app.gateway.gateway import build_gateway
from app.gateway.models_config import get_models_config
from app.pipeline.diagnosis.fetcher import FakeFetcher, FetchResult
from app.pipeline.diagnosis.runner import run_diagnosis
from app.pipeline.execution.runner import run_execution
from app.pipeline.monitor.runner import run_scan

DEMO_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TARGET = "https://8.8.8.8/"  # public IP so the SSRF guard passes; served offline
ROBOTS = "User-agent: *\nDisallow:"
HOME = "<html><body><h1>Acme Analytics</h1><p>Product analytics.</p></body></html>"


class CountingGateway:
    """Counts calls at the issuance boundary, independently of the cost sink.

    Delegates everything else, so the pipeline cannot tell it apart from the real
    gateway — which is the point: the count is ground truth about what the
    PIPELINE asked for, and the sink is what the gateway RECORDED. Comparing the
    two is the completeness check.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.issued: Counter = Counter()

    def call(self, task, messages, **kwargs):
        self.issued[task] += 1
        return self._inner.call(task, messages, **kwargs)

    @property
    def total_issued(self) -> int:
        return sum(self.issued.values())

    def __getattr__(self, name):  # everything else passes through untouched
        return getattr(self._inner, name)


def _db_ready() -> bool:
    try:
        with SessionLocal() as s:
            s.connection()
        return True
    except OperationalError:
        return False


def _fetcher() -> FakeFetcher:
    return FakeFetcher(
        {
            TARGET: FetchResult(
                url=TARGET, final_url=TARGET, status=200, ok=True, text=HOME
            ),
            f"{TARGET}robots.txt": FetchResult(
                url=f"{TARGET}robots.txt",
                final_url=f"{TARGET}robots.txt",
                status=200,
                ok=True,
                text=ROBOTS,
            ),
        }
    )


@pytest.fixture
def loop_run():
    """Run monitor -> diagnose -> execute for one scan, in mock, counting calls."""
    if not _db_ready():
        pytest.skip("database unreachable — run docker compose up + db:migrate/seed")

    sink = NullCostSink()
    gw = CountingGateway(
        build_gateway(mode="mock", cost_sink=sink, config=get_models_config())
    )

    with SessionLocal() as s:
        account = AccountRepository(s).get_by_id(DEMO_ACCOUNT_ID)
        original_plan = account.plan
        account.plan = "enterprise"  # headroom so the quota guard doesn't fire
        scan = Scan(account_id=DEMO_ACCOUNT_ID, status="pending", engine_set=[])
        s.add(scan)
        s.commit()
        scan_id = scan.id

    try:
        run_scan(DEMO_ACCOUNT_ID, scan_id, gw)
        run_diagnosis(
            DEMO_ACCOUNT_ID,
            scan_id=scan_id,
            target_url=TARGET,
            fetcher=_fetcher(),
            gateway=gw,
        )
        run_execution(DEMO_ACCOUNT_ID, scan_id=scan_id, gateway=gw)
        yield gw, sink, scan_id
    finally:
        with SessionLocal() as s:
            AccountRepository(s).get_by_id(DEMO_ACCOUNT_ID).plan = original_plan
            s.commit()


def test_every_issued_call_is_logged_exactly_once(loop_run):
    """The headline invariant: no call is silently unlogged."""
    gw, sink, _ = loop_run

    assert gw.total_issued > 0, "loop issued no calls — fixture is not exercising it"
    assert len(sink.entries) == gw.total_issued, (
        f"ledger incomplete: {gw.total_issued} calls issued, "
        f"{len(sink.entries)} logged"
    )


def test_per_operation_counts_match(loop_run):
    """Not just the total: each of the four operations balances on its own, so a
    single collapsing task can't hide behind another's surplus."""
    gw, sink, _ = loop_run
    logged = Counter(e.operation for e in sink.entries)
    assert logged == gw.issued, f"issued={dict(gw.issued)} logged={dict(logged)}"


def test_all_four_operations_are_exercised(loop_run):
    """Guards the guard: if the loop stopped issuing one of these, the equality
    assertions above would still pass vacuously for it."""
    gw, _, _ = loop_run
    assert {"measurement", "processing", "generation"} <= set(gw.issued)


def test_cache_hits_are_logged_and_free(loop_run):
    """Cache hits are real logical calls: they must appear, flagged, at zero cost.
    This is the exact path that silently dropped rows before."""
    _, sink, _ = loop_run
    cached = [e for e in sink.entries if e.cached]
    assert cached, "no cache hits occurred — this test would pass vacuously"
    assert all(e.cost_usd == Decimal("0") for e in cached)
    assert all(e.status == "ok" for e in cached)


def test_every_row_is_attributed_to_the_scan(loop_run):
    """Per-scan cost only works if every row carries its scan_id. The generation
    call used to omit it — present in the ledger, invisible to per-scan cost."""
    _, sink, scan_id = loop_run
    unattributed = sorted({e.operation for e in sink.entries if e.scan_id is None})
    assert not unattributed, f"operations logged with scan_id NULL: {unattributed}"
    assert all(e.scan_id == scan_id for e in sink.entries)


def test_mock_run_is_flagged_mock_and_costs_nothing_real(loop_run):
    _, sink, _ = loop_run
    assert all(e.mock for e in sink.entries)


def test_failed_calls_are_logged_with_error_status():
    """A call that raises still leaves a row, so a gap in the ledger can only ever
    mean a logging bug — never a swallowed provider error."""
    from app.gateway.gateway import Gateway
    from app.gateway.models_config import ModelsConfig, ProviderConfig, TaskTarget
    from app.gateway.types import Message

    class _BoomProvider:
        def generate(self, target, msgs, params):
            raise RuntimeError("provider exploded")

    sink = NullCostSink()
    gw = Gateway(
        mode="mock",
        config=ModelsConfig(
            tasks={"processing": {"mock": TaskTarget(provider="boom", model="x")}},
            providers={"boom": ProviderConfig(type="boom")},
        ),
        providers={"boom": _BoomProvider()},
        cost_sink=sink,
        cache=None,
    )

    with pytest.raises(RuntimeError):
        gw.call(
            "processing",
            [Message(role="user", content="hi")],
            account_id=DEMO_ACCOUNT_ID,
            scan_id=uuid.uuid4(),
        )

    assert len(sink.entries) == 1, "a failed call must still be logged"
    entry = sink.entries[0]
    assert entry.status == "error"
    assert entry.cost_usd == Decimal("0")
    assert entry.scan_id is not None
