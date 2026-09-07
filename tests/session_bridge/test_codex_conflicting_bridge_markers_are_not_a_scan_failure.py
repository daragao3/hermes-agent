"""A codex thread whose origin cannot be decided is unadoptable, not a scan failure.

The codex mirror of ``test_conflicting_bridge_markers_are_not_a_scan_failure``.
``codex_adapter._detect_origin`` raises ``ConflictingCodexBridgeMarkers`` when two
different bridge ids authenticate inside one thread, and the class has existed
since long before 2026-09-07 -- but no codex SCAN path caught it. Only the two
sidebar call sites inside ``codex_adapter`` did, so a conflicting thread reaching
``project_thread`` from a scan fell to the generic handler, exactly as the claude
side did until agent-src 9bb9461e29.

WHY THAT IS FATAL RATHER THAN COSMETIC: ``_scan_provider`` turns any nonzero
``ScanSummary.failed`` into ``degraded_reason=scan_failed`` for the whole
provider, on an axis carrying ``required_for_service_impact=true``. A failure also
re-stages the item, so ONE undecidable thread keeps ``failed`` nonzero on every
cycle and a service restart does not clear it -- measured on the claude side
2026-09-07, where it held ``session-bridge-service``, ``-catalog`` and
``-continuity`` red for hours. ``_scan_codex_persistent`` is worse still: its
generic handler RETURNS rather than continuing, so one such thread abandons the
rest of the batch AND leaves the id staged to be re-abandoned next cycle.

Codex is not failing this way today, which is the point -- this closes the gap
before it fires, and it is the same one-provider-has-a-handler asymmetry recorded
against 2026-08-13 and against the claude diagnostics, arriving for the third time.

ORIGIN IS DELIBERATELY NOT RECLASSIFIED. Deciding such a thread is really NATIVE
would let it index, but origin is HMAC-authenticated provenance feeding the
visibility and registration lanes. Skipping leaves that judgement to a human and
costs only what today already costs: the thread stays out of the catalog.

Both directions are pinned on all three paths. A conflict must stop degrading the
provider AND must still be reported; an ordinary index failure must STILL degrade.
Without that control, narrowing the clause could disarm the entire failure path
and every other test here would still pass.
"""

from __future__ import annotations

import logging

import pytest

from session_bridge.codex_adapter import (
    CodexThreadSummary,
    ConflictingCodexBridgeMarkers,
)
from session_bridge.config import BridgeConfig
from session_bridge.coordinator import SessionBridgeCoordinator
from session_bridge.models import BridgeMarkerPayload, Provider, SessionProjection
from session_bridge.store import redact_codex_thread_id


_NATIVE_ID = "01a04e30fab97b91911fe4c793a4dd55"


class _IndexFailure(RuntimeError):
    """An ordinary index failure -- the control that must STILL degrade."""


def _conflict() -> ConflictingCodexBridgeMarkers:
    return ConflictingCodexBridgeMarkers((
        BridgeMarkerPayload(
            bridge_id="sidebar:bridge-a",
            source_session_id="claude:source",
            target_provider=Provider.CODEX,
            policy_generation=1,
        ),
        BridgeMarkerPayload(
            bridge_id="sidebar:bridge-b",
            source_session_id="claude:source",
            target_provider=Provider.CODEX,
            policy_generation=1,
        ),
    ))


def _summary() -> CodexThreadSummary:
    return CodexThreadSummary(
        native_id=_NATIVE_ID,
        title=f"[Codex] {_NATIVE_ID}",
        cwd="C:/workspace/project",
        started_at=10.0,
        last_active=20.0,
        archived=False,
        revision="revision-1",
    )


class _RaisingCodexAdapter:
    """Raise from `project_thread`, where `_detect_origin` raises in production."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.projections = 0

    def list_inventory(self, *, archived: bool) -> list[object]:
        return [] if archived else [_summary()]

    def list_full_inventory(self, *, archived: bool) -> list[object]:
        return [] if archived else [_summary()]

    def find_native_thread(self, native_id: str, **kwargs: object) -> object | None:
        del kwargs
        return _summary() if native_id == _NATIVE_ID else None

    def project_thread(self, summary: object) -> SessionProjection:
        del summary
        self.projections += 1
        raise self._exc


class _IdleClaudeAdapter:
    def discover(self) -> list[object]:
        return []

    def list_inventory(self, *, archived: bool) -> list[object]:
        del archived
        return []


class _PersistentStore:
    """Routes to `_scan_codex_persistent`.

    `get_state`/`set_state` are REQUIRED, not incidental: `_scan_codex`
    dispatches on `_supports_scan_state(store)`, which duck-types on exactly
    those two attributes. A fake without them routes silently to
    `_scan_codex_immediate` -- a different function with its own counters -- so
    the test would assert about the wrong path while still passing. Every
    assertion below therefore also checks the `stage=` token in the diagnostic.
    """

    def __init__(self) -> None:
        self.states: dict[str, object] = {}

    def get_state(self, key: str) -> object:
        return self.states.get(key)

    def set_state(self, key: str, value: object) -> None:
        self.states[key] = value


class _ImmediateStore:
    """Routes to `_scan_codex_immediate` by HIDING the scan-state contract."""


def _coordinator(
    store: object, adapter: _RaisingCodexAdapter
) -> SessionBridgeCoordinator:
    return SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={
            Provider.CLAUDE: _IdleClaudeAdapter(),
            Provider.CODEX: adapter,
        },
    )


def _marker_lines(caplog: pytest.LogCaptureFixture, stage: str) -> list[str]:
    return [
        message
        for message in (record.getMessage() for record in caplog.records)
        if "codex_scan_diagnostic" in message
        and "code=codex_conflicting_bridge_markers" in message
        and f"stage={stage}" in message
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("store_factory", "stage"),
    [
        (_PersistentStore, "persistent_project"),
        (_ImmediateStore, "immediate_project"),
    ],
)
async def test_a_marker_conflict_does_not_degrade_the_incremental_paths(
    store_factory: type,
    stage: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The whole point: `failed` stays 0, so scan_failed never latches."""

    adapter = _RaisingCodexAdapter(_conflict())
    coordinator = _coordinator(store_factory(), adapter)

    with caplog.at_level(logging.INFO, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CODEX)

    assert adapter.projections >= 1, "the adapter must actually have been asked"
    assert summary.failed == 0, (
        "an undecidable origin is unadoptable, not a scan failure -- nonzero "
        "`failed` is what latches degraded_reason=scan_failed on the provider"
    )
    assert summary.indexed == 0, "it is still not cataloged; only the verdict changed"
    # Asserted AFTER `failed` so the red lands on the behaviour, but asserted:
    # a `failed == 0` obtained by silently routing to the other scan path (see
    # `_PersistentStore`) would otherwise read as a pass.
    assert _marker_lines(caplog, stage), (
        f"routed to the wrong scan path, or the skip was silent: "
        f"{[record.getMessage() for record in caplog.records]!r}"
    )


@pytest.mark.asyncio
async def test_a_marker_conflict_does_not_degrade_the_all_history_path() -> None:
    """`scan --all-history` reaches `_scan_all_codex_history` against the
    production store, so it is not a theoretical branch."""

    adapter = _RaisingCodexAdapter(_conflict())
    coordinator = _coordinator(_PersistentStore(), adapter)

    summary = await coordinator.scan_all_history(Provider.CODEX)

    assert adapter.projections >= 1
    assert summary.failed == 0
    assert summary.indexed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("store_factory", "stage"),
    [
        (_PersistentStore, "persistent_project"),
        (_ImmediateStore, "immediate_project"),
    ],
)
async def test_a_marker_conflict_is_still_reported(
    store_factory: type,
    stage: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Counted, never silent -- otherwise this trades a red row for a blind spot."""

    coordinator = _coordinator(store_factory(), _RaisingCodexAdapter(_conflict()))

    with caplog.at_level(logging.INFO, logger="session_bridge.coordinator"):
        await coordinator.scan_once(Provider.CODEX)

    matching = _marker_lines(caplog, stage)
    assert matching, "the skip must be reported, not silent"
    assert any("skipped=1" in message for message in matching), (
        f"the diagnostic must carry the count: {matching!r}"
    )
    tag = redact_codex_thread_id(_NATIVE_ID)
    assert tag is not None
    assert any(tag in message for message in matching), (
        f"and it must NAME the thread -- as the redacted tag every other codex "
        f"diagnostic uses, so an operator can correlate: {matching!r}"
    )


@pytest.mark.asyncio
async def test_a_marker_conflict_is_still_reported_on_the_all_history_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator = _coordinator(_PersistentStore(), _RaisingCodexAdapter(_conflict()))

    with caplog.at_level(logging.INFO, logger="session_bridge.coordinator"):
        await coordinator.scan_all_history(Provider.CODEX)

    matching = _marker_lines(caplog, "full_history_project")
    assert matching, "the skip must be reported, not silent"
    assert any("skipped=1" in message for message in matching)


@pytest.mark.asyncio
async def test_a_conflicting_thread_is_terminal_not_retried_forever() -> None:
    """`_scan_codex_persistent` alone carries a `terminal_ids` set, and a marker
    conflict belongs in it.

    Two authenticated bridge ids inside one thread is a permanent property of
    that thread's content, so a retry can only reproduce it. Leaving the id out
    would keep it outside the durable seen-set -- re-staged and re-skipped every
    cycle -- and would also hold the continuous frontier, which is the residue
    defect the deferral comments in this path already record. `deferred` is the
    counter for "try again"; this is not that.
    """

    coordinator = _coordinator(
        store := _PersistentStore(), _RaisingCodexAdapter(_conflict())
    )

    await coordinator.scan_once(Provider.CODEX)

    seen = store.states.get("session-bridge:scan:codex:seen") or {}
    assert _NATIVE_ID in (seen.get("native_ids") or ()), (
        "an undecidable thread can never resolve; only terminal ids may be "
        f"marked seen, and this one must be: {store.states!r}"
    )


@pytest.mark.asyncio
async def test_a_marker_conflict_does_not_record_a_scan_failure_error_code() -> None:
    """`_record_codex_scan_diagnostic` would have been the convenient reporter,
    but it hardcodes `codex_scan_failed` and pushes it into `recent_error_codes`.

    Using it here would move the false alarm from `ScanSummary.failed` into the
    health surface instead of removing it, which is why the aggregate block does
    its own logging.
    """

    coordinator = _coordinator(_PersistentStore(), _RaisingCodexAdapter(_conflict()))

    await coordinator.scan_once(Provider.CODEX)

    health = coordinator.health()
    assert "codex_scan_failed" not in health.get("recent_error_codes", ()), (
        "a skipped thread must not surface as a scan failure anywhere"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "store_factory",
    [_PersistentStore, _ImmediateStore],
)
async def test_an_ordinary_index_failure_still_degrades(store_factory: type) -> None:
    """The control. Without this, narrowing the clause could disarm the whole
    failure path and every one of these tests would still pass."""

    adapter = _RaisingCodexAdapter(_IndexFailure("boom"))
    coordinator = _coordinator(store_factory(), adapter)

    summary = await coordinator.scan_once(Provider.CODEX)

    assert adapter.projections >= 1
    assert summary.failed >= 1, (
        "only the marker conflict is exempt; a genuine failure must still count"
    )


@pytest.mark.asyncio
async def test_an_ordinary_index_failure_still_degrades_the_all_history_path() -> None:
    adapter = _RaisingCodexAdapter(_IndexFailure("boom"))
    coordinator = _coordinator(_PersistentStore(), adapter)

    summary = await coordinator.scan_all_history(Provider.CODEX)

    assert adapter.projections >= 1
    assert summary.failed >= 1


def test_the_exception_stays_a_valueerror_with_the_same_message() -> None:
    """Existing callers and tests match on ValueError and on the text; the class
    only lost its leading underscore so `coordinator` can import it."""

    exc = _conflict()
    assert isinstance(exc, ValueError)
    assert str(exc) == "Codex thread has conflicting bridge markers"
    assert len(exc.payloads) == 2
