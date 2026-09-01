from __future__ import annotations

import logging

import pytest

from session_bridge.codex_adapter import CodexThreadSummary
from session_bridge.config import BridgeConfig
from session_bridge.coordinator import SessionBridgeCoordinator
from session_bridge.models import Provider, SessionProjection


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

    def project_thread(self, summary: object) -> SessionProjection:
        del summary
        return self.projection


class _IdleClaudeAdapter:
    def discover(self) -> list[object]:
        return []

    def list_inventory(self, *, archived: bool) -> list[object]:
        del archived
        return []


class _ScanStateStore:
    """In-memory scan state.

    `_scan_codex` dispatches on `_supports_scan_state(store)` -- a store
    without get_state/set_state silently routes to _scan_codex_immediate
    instead, a DIFFERENT function with its own deferred log. A fake lacking
    these two methods therefore exercises the wrong path while looking like
    it exercises the right one.
    """

    def __init__(self) -> None:
        self.state: dict[str, object] = {}

    def get_state(self, key: str) -> object:
        return self.state.get(key)

    def set_state(self, key: str, value: object) -> None:
        self.state[key] = value


class _DeferringStore(_ScanStateStore):
    """Every upsert raises TimeoutError -- the app-server-timeout deferral.

    This is the branch `except (TimeoutError, StaleExternalProjection)` in
    _scan_codex_persistent, which increments `deferred` and `continue`s.
    """

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def upsert_projection(self, projection, *, rebuild: bool = False):
        del rebuild, projection
        self.attempts += 1
        raise TimeoutError("codex app-server request deadline exhausted")


@pytest.mark.asyncio
async def test_deferred_thread_is_logged_not_silently_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A deferral must leave an observable trace.

    `deferred` is not a ScanSummary field, so the log line is the ONLY signal
    that anything was deferred. It is also load-bearing: the `drained` guard
    requires `not deferred`, so a thread that defers every cycle pins the
    continuous frontier indefinitely. Without this log that stall is
    invisible -- failed=0, indexed=0, and nothing else to look at.

    The other two codex scan paths (full_history_project, immediate_project)
    have logged this since 2026-08-13; the persistent path did not.
    """

    store = _DeferringStore()
    coordinator = SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={
            Provider.CLAUDE: _IdleClaudeAdapter(),
            Provider.CODEX: _CodexAdapter(_projection("thread-deferred")),
        },
    )

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CODEX)

    assert store.attempts >= 1, "the store must actually have been asked"
    assert summary.failed == 0, "a deferral is benign and must not degrade"
    assert summary.indexed == 0, "nothing was cataloged"
    assert not [
        r for r in caplog.records if "stage=immediate_project" in r.getMessage()
    ], (
        "routed to _scan_codex_immediate, not _scan_codex_persistent -- the "
        "fake store must expose get_state/set_state or this asserts about "
        "the wrong function"
    )

    deferred_records = [
        record.getMessage()
        for record in caplog.records
        if "code=app_server_timeout" in record.getMessage()
    ]
    assert deferred_records, (
        "the persistent path deferred a thread and logged nothing; "
        "deferred is not on ScanSummary, so this line is the only signal"
    )
    message = deferred_records[0]
    assert "stage=persistent_project" in message, (
        f"wrong stage tag, cannot attribute the deferral: {message!r}"
    )
    assert "deferred=1" in message, f"deferral count not reported: {message!r}"


@pytest.mark.asyncio
async def test_clean_scan_does_not_emit_a_deferral_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Guard against the assertion above passing vacuously.

    If the line were emitted unconditionally it would carry no information,
    and the test above would pass on a build with the defect reintroduced
    in a different shape.
    """

    class _AcceptingStore(_ScanStateStore):
        def upsert_projection(self, projection, *, rebuild: bool = False):
            del rebuild, projection
            raise AssertionError("not reached: inventory is empty")

    coordinator = SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=_AcceptingStore(),
        adapters={
            Provider.CLAUDE: _IdleClaudeAdapter(),
            Provider.CODEX: _IdleClaudeAdapter(),
        },
    )

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        await coordinator.scan_once(Provider.CODEX)

    assert not [
        r for r in caplog.records if "code=app_server_timeout" in r.getMessage()
    ], "a scan that deferred nothing must not claim a deferral"
