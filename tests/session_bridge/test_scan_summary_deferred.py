"""`deferred` on the ScanSummary, mirroring `locally_owned` one field over.

A deferral is a thread the scan DECLINED to finish this cycle without failing:
`(TimeoutError, StaleExternalProjection)` from the codex app-server. It is
counted at every site and, since 2026-09-01, logged -- but it was dropped before
`ScanSummary`, so a caller saw `failed=0` with no way to tell a clean no-op scan
from one that left everything behind.

That is not merely cosmetic here. `_scan_codex_persistent` gates the continuous
frontier on `not deferred`:

    drained = (len(selected_ids) == len(staged_ids)
               and not deferred
               and terminal_ids >= set(staged_ids))

so a thread that defers every cycle PINS THE FRONTIER INDEFINITELY, and the
summary was the one place an operator could have seen why.

MUTATION-TESTED one site at a time (2026-09-02): each test below kills a
different wiring site, because a partial wiring is SILENTLY ZERO rather than an
error. In particular, dropping only the aggregate sum leaves the per-provider
summaries correct and prints `deferred=0` on the default `scan_once()` path an
operator actually runs.

ROUTING TRAP, inherited from the `locally_owned` twin: `_scan_codex` dispatches
on `_supports_scan_state(store)`, duck-typed on `get_state`/`set_state`. A fake
missing them does not fail -- it silently selects `_scan_codex_immediate`, a
different function with its own return site. Every test below states which path
it drives and proves it independently of the field under test.
"""

from __future__ import annotations

from typing import Any

import pytest

from session_bridge.codex_adapter import CodexThreadSummary
from session_bridge.config import BridgeConfig
from session_bridge.coordinator import SessionBridgeCoordinator
from session_bridge.models import Provider, SessionProjection
from tests.session_bridge.test_coordinator import (
    _CODEX_FRONTIER_KEY,
    _CODEX_SEEN_KEY,
    _BacklogCodexAdapter,
    _StateStore,
    _codex_summary,
)


class _IdleClaudeAdapter:
    def discover(self) -> list[object]:
        return []

    def list_inventory(self, *, archived: bool) -> list[object]:
        del archived
        return []


class _DeferringCodexAdapter(_BacklogCodexAdapter):
    """Continuous-scan adapter whose named threads time out in `project_thread`.

    A timeout describes the HOST, not the thread, so the coordinator defers it:
    no failure, no terminal id, and the thread stays stageable next cycle.
    """

    def __init__(
        self,
        summaries: list[CodexThreadSummary],
        *,
        deferring: set[str],
        operations: list[tuple[object, ...]],
    ) -> None:
        super().__init__(
            inventory_batches=[list(summaries)],
            summaries_by_native_id={
                summary.native_id: summary for summary in summaries
            },
            operations=operations,
        )
        self._summaries = list(summaries)
        self._deferring = set(deferring)

    def list_full_inventory(
        self,
        *,
        archived: bool,
    ) -> list[CodexThreadSummary]:
        return [] if archived else list(self._summaries)

    def list_recent_inventory(
        self,
        *,
        archived: bool,
        after: float,
    ) -> list[CodexThreadSummary]:
        del after
        return [] if archived else list(self._summaries)

    def project_thread(self, summary: CodexThreadSummary) -> SessionProjection:
        if summary.native_id in self._deferring:
            raise TimeoutError("codex app-server did not answer")
        return super().project_thread(summary)


def _persistent_coordinator(
    summaries: list[CodexThreadSummary],
    *,
    deferring: set[str],
    fail_upsert_number: int | None = None,
) -> tuple[SessionBridgeCoordinator, _StateStore]:
    operations: list[tuple[object, ...]] = []
    adapter = _DeferringCodexAdapter(
        summaries,
        deferring=deferring,
        operations=operations,
    )
    store = _StateStore(operations, fail_upsert_number=fail_upsert_number)
    coordinator = SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={
            Provider.CLAUDE: _IdleClaudeAdapter(),
            Provider.CODEX: adapter,
        },
    )
    coordinator._continuous_watermark = 250.0
    store.states[_CODEX_SEEN_KEY] = {"version": 1, "native_ids": ["codex-known"]}
    return coordinator, store


def _assert_took_the_persistent_path(store: _StateStore) -> None:
    """`_scan_codex_immediate` writes no scan state; the persistent path does."""

    assert any(key.startswith("session-bridge:scan:codex:") for key in store.states), (
        "no codex scan state was written: this ran _scan_codex_immediate, and "
        "the assertions below would be made against the wrong return site"
    )


@pytest.mark.asyncio
async def test_persistent_deferral_survives_to_the_scan_summary() -> None:
    """Kills the FINAL return of `_scan_codex_persistent`.

    That return is the one a healthy bridge takes every cycle, and it is the
    return whose own `drained` gate the deferral just held.
    """

    coordinator, store = _persistent_coordinator(
        [_codex_summary("codex-deferred", 300.0)],
        deferring={"codex-deferred"},
    )

    summary = await coordinator.scan_once(Provider.CODEX)

    _assert_took_the_persistent_path(store)
    assert summary.failed == 0, "a deferral describes the host, not the thread"
    assert summary.indexed == 0, "nothing was cataloged"
    assert summary.deferred == 1, (
        "the deferral must survive to the summary; failed=0 alone reads as "
        "'nothing was left behind'"
    )
    # The state the summary is now able to explain.
    assert _CODEX_FRONTIER_KEY not in store.states, (
        "a deferral must hold the continuous frontier"
    )


@pytest.mark.asyncio
async def test_persistent_failure_return_still_reports_the_deferral() -> None:
    """Kills the EARLY (failed=1) return of `_scan_codex_persistent`.

    Two returns, two chances to drop the field. This one abandons the rest of
    the batch, so the deferral it already counted is exactly the context an
    operator needs -- and it is the return a partial wiring is most likely to
    miss.
    """

    coordinator, store = _persistent_coordinator(
        [
            _codex_summary("codex-deferred", 320.0),
            _codex_summary("codex-explodes", 300.0),
        ],
        deferring={"codex-deferred"},
        fail_upsert_number=1,
    )

    summary = await coordinator.scan_once(Provider.CODEX)

    _assert_took_the_persistent_path(store)
    assert summary.failed == 1, "the generic handler must still report a failure"
    assert summary.deferred == 1, (
        "the early return dropped the deferral it had already counted"
    )


@pytest.mark.asyncio
async def test_all_provider_aggregate_sums_deferred() -> None:
    """Kills the `scan_once()` aggregate sum.

    The aggregate rebuilds ScanSummary field by field, so a field missing from
    it reads as a clean zero on the default provider=None path an operator
    actually runs -- while every per-provider summary is correct.
    """

    coordinator, store = _persistent_coordinator(
        [_codex_summary("codex-deferred", 300.0)],
        deferring={"codex-deferred"},
    )

    summary = await coordinator.scan_once()

    _assert_took_the_persistent_path(store)
    assert summary.provider is None
    assert summary.failed == 0
    assert summary.deferred == 1


@pytest.mark.asyncio
async def test_immediate_path_deferral_survives_to_the_scan_summary() -> None:
    """Kills the `_scan_codex_immediate` return.

    A store without `get_state`/`set_state` routes here silently -- the fake
    below is under-implemented ON PURPOSE, which is what selects this branch.
    """

    class _StatelessStore:
        def __init__(self) -> None:
            self.attempts = 0

        def upsert_projection(
            self,
            projection: SessionProjection,
            *,
            rebuild: bool = False,
        ) -> Any:
            del projection, rebuild
            self.attempts += 1
            raise AssertionError("the deferral happens before any upsert")

    operations: list[tuple[object, ...]] = []
    adapter = _DeferringCodexAdapter(
        [_codex_summary("codex-deferred", 300.0)],
        deferring={"codex-deferred"},
        operations=operations,
    )
    store = _StatelessStore()
    coordinator = SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={
            Provider.CLAUDE: _IdleClaudeAdapter(),
            Provider.CODEX: adapter,
        },
    )

    summary = await coordinator.scan_once(Provider.CODEX)

    assert not hasattr(store, "get_state"), "this test owns the immediate route"
    assert summary.failed == 0
    assert summary.deferred == 1


def _full_history_coordinator() -> SessionBridgeCoordinator:
    operations: list[tuple[object, ...]] = []
    adapter = _DeferringCodexAdapter(
        [_codex_summary("codex-deferred", 300.0)],
        deferring={"codex-deferred"},
        operations=operations,
    )
    return SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=_StateStore(operations),
        adapters={
            Provider.CLAUDE: _IdleClaudeAdapter(),
            Provider.CODEX: adapter,
        },
    )


@pytest.mark.asyncio
async def test_full_history_deferral_survives_to_the_scan_summary() -> None:
    """Kills `_scan_all_codex_history` AND the `_scan_all_history_provider`
    wrapper passthrough -- a separate wrapper from the incremental one, with its
    own field-by-field rebuild that every full-history caller funnels through.
    """

    coordinator = _full_history_coordinator()

    summary = await coordinator.scan_all_history(Provider.CODEX)

    assert summary.provider is Provider.CODEX
    assert summary.duration_ms >= 0, "wrapper-built summary, not the inner one"
    assert summary.failed == 0
    assert summary.deferred == 1


@pytest.mark.asyncio
async def test_all_provider_full_history_aggregate_sums_deferred() -> None:
    """Kills the `scan_all_history()` aggregate sum -- a SECOND, separate sum.

    `scan_once()` and `scan_all_history()` each rebuild the provider=None
    summary with their own explicit field list, so wiring one and not the other
    is invisible: the incremental aggregate test above still passes while a
    full-inventory rebuild reports deferred=0.
    """

    coordinator = _full_history_coordinator()

    summary = await coordinator.scan_all_history()

    assert summary.provider is None
    assert summary.failed == 0
    assert summary.deferred == 1
