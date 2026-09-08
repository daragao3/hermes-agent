"""A benign codex scan branch must not publish `codex_scan_failed`.

`_record_codex_scan_diagnostic` hardcoded `_CODEX_SCAN_FAILURE_CODE` in both
its log line and its final `_record_error_code` call, and took no code
parameter. FOUR of its seven call sites are branches that deliberately do NOT
increment `ScanSummary.failed`: the three `(TimeoutError,
StaleExternalProjection)` deferrals, and the vanished-staged-thread branch in
`_scan_codex_persistent`. All four therefore pushed `codex_scan_failed` into
`recent_error_codes`.

WHY THAT LIST IS NOT ADVISORY. `session_bridge.health` admits the coordinator's
`recent_error_codes` as a `mirror_jobs` failure, and its registry maps
("mirror_jobs", "codex_scan_failed") -> ("provider", "index_refresh_blocked",
"retryable"). So a host-side app-server timeout published "the index refresh is
blocked" about a healthy service. It is also a 20-slot UN-deduped FIFO admitted
FIRST against MAX_FAILURES=32, so a recurring benign condition crowds
sidebar/hydration/visibility evidence out of the envelope -- the displacement is
the real cost, not the label.

This is the same false-alarm shape 1cb03b2775 removed from `ScanSummary.failed`
for marker conflicts, one layer up in the health surface. It is exactly why the
marker-conflict skip routes around this helper
(`test_a_marker_conflict_does_not_record_a_scan_failure_error_code`).

THE CONTROLS BELOW ARE LOAD-BEARING. Narrowing what reaches `_record_error_code`
could disarm the genuine failure path with every other test still green, so a
real index failure must STILL record the code, and an unrecognised diagnostic
code must degrade TOWARD reporting rather than toward silence.
"""

from __future__ import annotations

import logging

import pytest

from session_bridge.codex_adapter import CodexThreadSummary
from session_bridge.config import BridgeConfig
from session_bridge.coordinator import SessionBridgeCoordinator
from session_bridge.models import Provider, SessionProjection

_FAILURE_CODE = "codex_scan_failed"
_DEFERRED_CODE = "codex_scan_deferred"
_VANISHED_CODE = "codex_scan_thread_vanished"


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
    """Inventory of exactly one thread, projected without complaint."""

    def __init__(self, projection: SessionProjection) -> None:
        self.projection = projection

    def list_inventory(self, *, archived: bool) -> list[object]:
        if archived:
            return []
        return [
            CodexThreadSummary(
                native_id=self.projection.native_id,
                title=self.projection.title,
                cwd=self.projection.cwd,
                started_at=10.0,
                last_active=self.projection.last_active,
                archived=False,
                revision="revision-1",
            )
        ]

    def list_full_inventory(self, *, archived: bool) -> list[object]:
        # `_scan_all_codex_history` goes through `_codex_full_inventory`, which
        # calls THIS, not `list_inventory`. An adapter missing it raises out as
        # an ordinary scan failure before the deferral branch is ever reached.
        return self.list_inventory(archived=archived)

    def project_thread(self, summary: object) -> SessionProjection:
        del summary
        return self.projection


class _VanishedCodexAdapter:
    """Empty inventory; a staged id no longer resolves at the source.

    This is the `summary is None` branch of `_scan_codex_persistent` -- a
    thread deleted, archived out of scope, or pruned since it was staged.
    """

    def list_inventory(self, *, archived: bool) -> list[object]:
        del archived
        return []

    def find_native_thread(self, native_id: str, **kwargs: object) -> None:
        del native_id, kwargs
        return None


class _IdleAdapter:
    def discover(self) -> list[object]:
        return []

    def list_inventory(self, *, archived: bool) -> list[object]:
        del archived
        return []


class _ScanStateStore:
    """In-memory scan state.

    `_scan_codex` dispatches on `_supports_scan_state(store)`: a store WITHOUT
    get_state/set_state routes silently to `_scan_codex_immediate`, a different
    function. An under-implemented fake does not fail -- it selects the other
    branch -- so the tests below assert which stage tag they saw rather than
    trusting the route.
    """

    def __init__(self) -> None:
        self.state: dict[str, object] = {}

    def get_state(self, key: str) -> object:
        return self.state.get(key)

    def set_state(self, key: str, value: object) -> None:
        self.state[key] = value


class _StatelessStore:
    """No get_state/set_state -- routes codex scans to the IMMEDIATE path."""


class _DeferringMixin:
    """Every upsert raises TimeoutError: the app-server-timeout deferral."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def upsert_projection(self, projection: object, *, rebuild: bool = False) -> object:
        del rebuild, projection
        self.attempts += 1
        raise TimeoutError("codex app-server request deadline exhausted")


class _DeferringStatefulStore(_DeferringMixin, _ScanStateStore):
    pass


class _DeferringStatelessStore(_DeferringMixin, _StatelessStore):
    pass


class _FailingStore(_ScanStateStore):
    """Every upsert raises an ordinary error: a GENUINE scan failure."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def upsert_projection(self, projection: object, *, rebuild: bool = False) -> object:
        del rebuild, projection
        self.attempts += 1
        raise ValueError("codex projection could not be stored")


def _coordinator(store: object, codex_adapter: object) -> SessionBridgeCoordinator:
    return SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={Provider.CLAUDE: _IdleAdapter(), Provider.CODEX: codex_adapter},
    )


def _diagnostics(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if "codex_scan_diagnostic" in record.getMessage()
    ]


@pytest.mark.asyncio
async def test_a_persistent_deferral_does_not_record_a_scan_failure_error_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _DeferringStatefulStore()
    coordinator = _coordinator(store, _CodexAdapter(_projection("thread-deferred")))

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CODEX)

    assert store.attempts >= 1, "the store must actually have been asked"
    assert summary.failed == 0, "a deferral is benign and must not degrade"
    assert summary.deferred == 1, "the deferral must still be counted"

    messages = _diagnostics(caplog)
    assert any("stage=persistent_project" in m for m in messages), (
        "routed to the wrong scan function -- the fake store must expose "
        f"get_state/set_state, saw: {messages!r}"
    )
    assert coordinator.health()["recent_error_codes"] == [], (
        "a host-side timeout published a provider failure claiming the codex "
        "index refresh is blocked, on a service that is fine"
    )
    assert any(f"code={_DEFERRED_CODE}" in m for m in messages), (
        f"the deferral must still name itself in the log: {messages!r}"
    )


@pytest.mark.asyncio
async def test_an_immediate_deferral_does_not_record_a_scan_failure_error_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _DeferringStatelessStore()
    coordinator = _coordinator(store, _CodexAdapter(_projection("thread-immediate")))

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CODEX)

    assert store.attempts >= 1, "the store must actually have been asked"
    assert summary.failed == 0
    messages = _diagnostics(caplog)
    assert any("stage=immediate_project" in m for m in messages), (
        f"did not reach _scan_codex_immediate, saw: {messages!r}"
    )
    assert coordinator.health()["recent_error_codes"] == []
    assert any(f"code={_DEFERRED_CODE}" in m for m in messages)


@pytest.mark.asyncio
async def test_a_full_history_deferral_does_not_record_a_scan_failure_error_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _DeferringStatefulStore()
    coordinator = _coordinator(store, _CodexAdapter(_projection("thread-history")))

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_all_history(Provider.CODEX)

    assert store.attempts >= 1, "the store must actually have been asked"
    assert summary.failed == 0
    messages = _diagnostics(caplog)
    assert any("stage=full_history_project" in m for m in messages), (
        f"did not reach _scan_all_codex_history, saw: {messages!r}"
    )
    assert coordinator.health()["recent_error_codes"] == []
    assert any(f"code={_DEFERRED_CODE}" in m for m in messages)


@pytest.mark.asyncio
async def test_a_vanished_staged_thread_does_not_record_a_scan_failure_error_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fourth benign site, and the one that is TERMINAL rather than deferred.

    A staged id the source can no longer resolve enters `terminal_ids` and is
    drained. It can never resolve, so reporting it as a scan failure is a
    permanent false alarm rather than a transient one.
    """

    store = _ScanStateStore()
    store.state["session-bridge:scan:codex:pending"] = {
        "version": 1,
        "native_ids": ["thread-gone"],
    }
    coordinator = _coordinator(store, _VanishedCodexAdapter())

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CODEX)

    assert summary.failed == 0, "a vanished thread is not a scan failure"
    messages = _diagnostics(caplog)
    assert any(f"code={_VANISHED_CODE}" in m for m in messages), (
        f"the vanished branch was not reached or did not name itself: {messages!r}"
    )
    assert coordinator.health()["recent_error_codes"] == [], (
        "a thread deleted at the source published a provider failure claiming "
        "the codex index refresh is blocked"
    )


@pytest.mark.asyncio
async def test_a_genuine_index_failure_still_records_the_scan_failure_error_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CONTROL. Narrowing what reaches `_record_error_code` must not disarm
    the real failure path -- that regression would leave every other test in
    this file green.
    """

    store = _FailingStore()
    coordinator = _coordinator(store, _CodexAdapter(_projection("thread-broken")))

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CODEX)

    assert store.attempts >= 1
    assert summary.failed == 1, "an ordinary error must still degrade the provider"
    assert _FAILURE_CODE in coordinator.health()["recent_error_codes"], (
        "a real codex scan failure stopped reaching the health surface"
    )
    assert any(f"code={_FAILURE_CODE}" in m for m in _diagnostics(caplog)), (
        "the diagnostic helper stopped naming genuine failures"
    )


@pytest.mark.asyncio
async def test_an_unrecognised_diagnostic_code_degrades_to_the_failure_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CONTROL. The `code=` parameter must fail TOWARD reporting.

    A future call site passing an unknown code must be reported as a failure,
    never silently dropped from the health surface -- the same direction
    `safe_stage` already takes.
    """

    coordinator = _coordinator(_ScanStateStore(), _IdleAdapter())

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        coordinator._record_codex_scan_diagnostic(
            stage="persistent_project",
            native_id="thread-unknown-code",
            exc=RuntimeError("boom"),
            adapter=_IdleAdapter(),
            code="not_a_registered_diagnostic_code",
        )

    messages = _diagnostics(caplog)
    assert any(f"code={_FAILURE_CODE}" in m for m in messages), (
        f"an unknown code must degrade to the failure code: {messages!r}"
    )
    assert not any("not_a_registered_diagnostic_code" in m for m in messages), (
        "an unvalidated code reached the log"
    )
    assert coordinator.health()["recent_error_codes"] == [_FAILURE_CODE], (
        "an unknown code must still be reported, not silently swallowed"
    )
