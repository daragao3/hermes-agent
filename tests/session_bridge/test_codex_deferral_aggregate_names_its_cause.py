"""The aggregate `if deferred:` line must name the cause it actually observed.

All three codex scan paths end their per-thread loop with an aggregate block
that logged `code=app_server_timeout` UNCONDITIONALLY. But the branch that
increments `deferred` catches two disjoint types:

* ``TimeoutError`` -- the codex app-server did not answer inside its bound. A
  statement about the HOST.
* ``StaleExternalProjection`` -- the incoming projection is older than the
  persisted activity watermark. Its own docstring: "a no-op, not corruption".
  Nothing is wrong with the app server at all.

Those have opposite remediations, so an operator reading the log during an
incident was told to go look at a subsystem that may be perfectly healthy.

WHY THIS IS NOT THE SAME QUESTION AS `codex_scan_deferred`. The PER-OCCURRENCE
line names a CATEGORY (`codex_scan_deferred`, f0bcce6ced) and the aggregate
names a CAUSE. That pair is deliberate and this file must not collapse it --
tagging the aggregate `codex_scan_deferred` too would throw the cause away,
which is the information the aggregate exists to carry. See
`test_codex_scan_deferral_is_not_a_health_surface_failure` for the category
half, whose behaviour these tests must leave untouched.

SCOPE: the diagnostic log `code=` is free text that nothing outside
`coordinator.py` consumes. Deliberately NO health-surface vocabulary is added
here -- the deferral branches do not call `_record_error_code` at all, and that
surface has been blinded twice by one-sided vocabulary additions.
"""

from __future__ import annotations

import logging

import pytest

from session_bridge.codex_adapter import CodexThreadSummary
from session_bridge.config import BridgeConfig
from session_bridge.coordinator import (
    _CODEX_DEFERRAL_MIXED_CAUSE,
    _CODEX_DEFERRAL_STALE_CAUSE,
    _CODEX_DEFERRAL_TIMEOUT_CAUSE,
    _CODEX_DEFERRAL_UNKNOWN_CAUSE,
    SessionBridgeCoordinator,
    _codex_deferral_cause,
)
from session_bridge.models import Provider, SessionProjection
from session_bridge.store import StaleExternalProjection

_TIMEOUT_ID = "thread-timeout"
_STALE_ID = "thread-stale"


def _projection(native_id: str) -> SessionProjection:
    return SessionProjection(
        provider=Provider.CODEX,
        native_id=native_id,
        title=f"[Codex] {native_id}",
        cwd="C:/workspace/project",
        started_at=10.0,
        last_active=20.0,
        messages=(),
        native_cursor="revision-1",
        native_hash="hash-1",
    )


class _CodexAdapter:
    """Inventory of the given native ids, each projected without complaint."""

    def __init__(self, *native_ids: str) -> None:
        self.native_ids = native_ids

    def list_inventory(self, *, archived: bool) -> list[object]:
        if archived:
            return []
        return [
            CodexThreadSummary(
                native_id=native_id,
                title=f"[Codex] {native_id}",
                cwd="C:/workspace/project",
                started_at=10.0,
                last_active=20.0,
                archived=False,
                revision="revision-1",
            )
            for native_id in self.native_ids
        ]

    def list_full_inventory(self, *, archived: bool) -> list[object]:
        # `_scan_all_codex_history` reaches the adapter through
        # `_codex_full_inventory`, which calls THIS, not `list_inventory`. An
        # adapter missing it raises out as an ordinary scan failure BEFORE the
        # deferral branch is reached, so the test would assert about a branch
        # it never entered.
        return self.list_inventory(archived=archived)

    def project_thread(self, summary: object) -> SessionProjection:
        return _projection(str(getattr(summary, "native_id", "")))


class _IdleAdapter:
    def discover(self) -> list[object]:
        return []

    def list_inventory(self, *, archived: bool) -> list[object]:
        del archived
        return []


class _ScanStateStore:
    """In-memory scan state -- routes codex scans to the PERSISTENT path.

    `_scan_codex` dispatches on `_supports_scan_state(store)`: a store WITHOUT
    get_state/set_state routes silently to `_scan_codex_immediate`, a different
    function with its own aggregate line. Every test below asserts which stage
    tag it saw rather than trusting the route.
    """

    def __init__(self) -> None:
        self.state: dict[str, object] = {}
        self.attempts = 0

    def get_state(self, key: str) -> object:
        return self.state.get(key)

    def set_state(self, key: str, value: object) -> None:
        self.state[key] = value

    def upsert_projection(self, projection: object, *, rebuild: bool = False) -> object:
        del rebuild
        self.attempts += 1
        native_id = str(getattr(projection, "native_id", ""))
        if native_id == _STALE_ID:
            raise StaleExternalProjection("last_active moved backwards by 13s")
        raise TimeoutError("codex app-server request deadline exhausted")


class _StatelessStore(_ScanStateStore):
    """No get_state/set_state -- routes codex scans to the IMMEDIATE path."""

    get_state = None  # type: ignore[assignment]
    set_state = None  # type: ignore[assignment]


def _coordinator(store: object, adapter: object) -> SessionBridgeCoordinator:
    return SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={Provider.CLAUDE: _IdleAdapter(), Provider.CODEX: adapter},
    )


def _aggregate(caplog: pytest.LogCaptureFixture, stage: str) -> str:
    """The one aggregate deferral line for `stage`.

    Distinguished from the per-occurrence diagnostic by `deferred=`, which only
    the aggregate carries. Asserting on any `codex_scan_diagnostic` line would
    silently match the per-occurrence line and prove nothing about the cause.
    """

    lines = [
        record.getMessage()
        for record in caplog.records
        if f"codex_scan_diagnostic stage={stage} " in record.getMessage()
        and "deferred=" in record.getMessage()
    ]
    assert len(lines) == 1, (
        f"expected exactly one aggregate deferral line for {stage}, saw: "
        f"{[r.getMessage() for r in caplog.records]!r}"
    )
    return lines[0]


@pytest.mark.asyncio
async def test_a_stale_projection_is_not_reported_as_an_app_server_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE DEFECT. A stale projection said the app server timed out.

    This is the only test in the file that fails against the unconditional
    line; the timeout control below passes either way by construction.
    """

    store = _ScanStateStore()
    coordinator = _coordinator(store, _CodexAdapter(_STALE_ID))

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CODEX)

    assert store.attempts >= 1, "the store must actually have been asked"
    assert summary.failed == 0, "a stale projection is benign and must not degrade"
    assert summary.deferred == 1, "the deferral must still be counted"

    message = _aggregate(caplog, "persistent_project")
    assert f"code={_CODEX_DEFERRAL_STALE_CAUSE}" in message, (
        f"the aggregate did not name the cause it observed: {message!r}"
    )
    assert _CODEX_DEFERRAL_TIMEOUT_CAUSE not in message, (
        "nothing timed out -- a stale projection is a no-op about the "
        f"watermark, not a statement about the app server: {message!r}"
    )
    assert "deferred=1 timeouts=0 stale=1" in message, (
        f"the cause breakdown is wrong or missing: {message!r}"
    )


@pytest.mark.asyncio
async def test_a_timeout_deferral_still_reports_app_server_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CONTROL -- do not delete. The fix must not cost the true-positive tag.

    `app_server_timeout` is the string an operator greps for and it predates
    this change, so narrowing the cause must leave the genuine timeout case
    byte-compatible on `code=`. A fix that renamed every deferral to a new
    neutral tag would pass the stale test above and silently break every
    existing search and runbook.
    """

    store = _ScanStateStore()
    coordinator = _coordinator(store, _CodexAdapter(_TIMEOUT_ID))

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CODEX)

    assert store.attempts >= 1
    assert summary.failed == 0
    message = _aggregate(caplog, "persistent_project")
    assert f"code={_CODEX_DEFERRAL_TIMEOUT_CAUSE}" in message, (
        f"the genuine timeout lost its historical tag: {message!r}"
    )
    assert "deferred=1 timeouts=1 stale=0" in message, (
        f"the cause breakdown is wrong or missing: {message!r}"
    )


@pytest.mark.asyncio
async def test_both_causes_in_one_cycle_report_the_mixed_tag_and_the_breakdown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One aggregate line, two causes: the tag must not pick a winner.

    The breakdown is what makes `mixed_deferral_causes` actionable. Without it
    the reader is exactly as badly off as with the unconditional tag, so the
    counts are asserted here rather than left to the single-cause tests.
    """

    store = _ScanStateStore()
    coordinator = _coordinator(store, _CodexAdapter(_TIMEOUT_ID, _STALE_ID))

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CODEX)

    assert summary.failed == 0
    assert summary.deferred == 2, "both threads must have deferred"

    message = _aggregate(caplog, "persistent_project")
    assert f"code={_CODEX_DEFERRAL_MIXED_CAUSE}" in message, (
        f"a mixed cycle asserted a single cause: {message!r}"
    )
    assert "deferred=2 timeouts=1 stale=1" in message, (
        f"the mixed tag without a usable breakdown: {message!r}"
    )


@pytest.mark.asyncio
async def test_the_immediate_path_names_its_cause_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per-site coverage: the three aggregate blocks are separate code.

    They are textually identical today, so one test would look like enough --
    but a merge dropping the change at one site is exactly the regression this
    file exists to catch, and the surviving sites would keep it green.
    """

    store = _StatelessStore()
    coordinator = _coordinator(store, _CodexAdapter(_STALE_ID))

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CODEX)

    assert store.attempts >= 1
    assert summary.failed == 0
    message = _aggregate(caplog, "immediate_project")
    assert f"code={_CODEX_DEFERRAL_STALE_CAUSE}" in message, (
        f"_scan_codex_immediate still asserts a timeout: {message!r}"
    )
    assert "deferred=1 timeouts=0 stale=1" in message


@pytest.mark.asyncio
async def test_the_full_history_path_names_its_cause_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per-site coverage for `_scan_all_codex_history`. See the test above."""

    store = _ScanStateStore()
    coordinator = _coordinator(store, _CodexAdapter(_STALE_ID))

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_all_history(Provider.CODEX)

    assert store.attempts >= 1
    assert summary.failed == 0
    message = _aggregate(caplog, "full_history_project")
    assert f"code={_CODEX_DEFERRAL_STALE_CAUSE}" in message, (
        f"_scan_all_codex_history still asserts a timeout: {message!r}"
    )
    assert "deferred=1 timeouts=0 stale=1" in message


def test_an_uncounted_deferral_cause_is_named_not_defaulted_to_timeout() -> None:
    """DRIFT GUARD -- do not delete, and do not "simplify" the default away.

    Unreachable through the scan paths today: the catch tuple has exactly the
    two types both counters cover. It becomes reachable the moment a third type
    joins that tuple without a counter, and the tempting shape there --
    `return TIMEOUT` as the fallback -- silently reinstates the original defect
    for the new type. So the fallback names the drift instead.
    """

    assert _codex_deferral_cause(0, 0) == _CODEX_DEFERRAL_UNKNOWN_CAUSE
    assert _codex_deferral_cause(1, 0) == _CODEX_DEFERRAL_TIMEOUT_CAUSE
    assert _codex_deferral_cause(0, 1) == _CODEX_DEFERRAL_STALE_CAUSE
    assert _codex_deferral_cause(1, 1) == _CODEX_DEFERRAL_MIXED_CAUSE
