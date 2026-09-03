"""`locally_owned` on the two remaining CLAUDE scan paths.

`_scan_claude_persistent` has caught `LocalSessionOwnsCanonicalId` since
2026-08-13 and reported it since 2026-09-02. `_scan_claude_immediate` and
`_scan_all_claude_history` had NO handler at all, so the exception fell to their
generic `except Exception` and the transcript was counted as a FAILURE --
measured 2026-09-02 as `ScanSummary(provider=claude, discovered=1, indexed=0,
failed=1, locally_owned=0)`.

WHY THAT MATTERS ON THE ALL-HISTORY PATH SPECIFICALLY. It is the only claude
path that is NOT gated on `_supports_scan_state`, so `session-bridge scan
--all-history` reaches it against the real production store. Measured on the
live catalog (~/.hermes/state.db) 2026-09-03: 335 claude `sessions` rows have no
`external_sessions` row (all rowid<=3523), and exactly ONE of them still has a
transcript on disk for `discover` to find --
claude:5dc2e902-01ad-4dee-9a5d-45cedd83346e, the session already named in
`_scan_claude_persistent`. `_scan_all_history_provider` turns any
`summary.failed` into `degraded_reason=scan_failed` for the whole provider, and
the local row is never adopted, so that degradation was permanent.

This is a BEHAVIOUR change, not a reporting one: `failed` drops on both paths.

ROUTING TRAP. `_scan_claude` dispatches on `_supports_scan_state(store)`, which
duck-types `get_state`/`set_state`. A fake missing them does not fail -- it
SELECTS `_scan_claude_immediate`, a different function. So every test here
asserts WHICH implementation ran by spying on the coroutines themselves, rather
than inferring it from counts: the persistent path is replaced with a spy that
raises, so a misroute cannot masquerade as a pass in either direction.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from hermes_state import SessionDB
from session_bridge.claude_adapter import ClaudeSourceAdapter
from session_bridge.config import BridgeConfig
from session_bridge.coordinator import SessionBridgeCoordinator
from session_bridge.models import Provider
from session_bridge.store import (
    LocalSessionOwnsCanonicalId,
    SessionBridgeStore,
    StaleExternalProjection,
)


_MARKER_SECRET = b"synthetic-locally-owned-claude-paths-secret"


def _record(native_id: str, index: int) -> bytes:
    return (
        json.dumps(
            {
                "type": "user",
                "sessionId": native_id,
                "uuid": f"event-{native_id}-{index:04d}",
                "timestamp": f"2026-09-03T10:00:{index % 60:02d}Z",
                "cwd": "C:/synthetic/claude",
                "gitBranch": "main",
                "isSidechain": False,
                "message": {"role": "user", "content": f"message {index:04d}"},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


class _DecliningStore:
    """A real store whose every upsert collides, delegating everything else."""

    def __init__(self, inner: SessionBridgeStore, exc: type[Exception]) -> None:
        self._inner = inner
        self._exc = exc
        self.attempts = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def upsert_projection(self, projection: Any, *, rebuild: bool = False) -> Any:
        del rebuild
        self.attempts += 1
        raise self._exc(f"local session owns claude:{projection.native_id}")


class _StatelessDecliningStore(_DecliningStore):
    """Same, but with `get_state`/`set_state` hidden.

    This is the ONLY thing that selects `_scan_claude_immediate`, and hiding
    them has to be explicit: `_DecliningStore.__getattr__` would otherwise
    delegate both through to the real store and route to the persistent path.
    """

    _HIDDEN = frozenset({"get_state", "set_state"})

    def __getattr__(self, name: str) -> Any:
        if name in self._HIDDEN:
            raise AttributeError(name)
        return super().__getattr__(name)


def _build(
    tmp_path: Path,
    store_cls: type[_DecliningStore] = _DecliningStore,
    exc: type[Exception] = LocalSessionOwnsCanonicalId,
) -> tuple[SessionBridgeCoordinator, _DecliningStore]:
    root = tmp_path / "projects"
    transcript = root / "project" / "claude-collision.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(b"".join(_record("claude-collision", i) for i in range(3)))
    db = SessionDB(db_path=tmp_path / "state.db")
    store = store_cls(SessionBridgeStore(db, clock=lambda: 1_000.0), exc)
    coordinator = SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={
            Provider.CLAUDE: ClaudeSourceAdapter(root, marker_secret=_MARKER_SECRET)
        },
    )
    return coordinator, store


def _spy(monkeypatch: pytest.MonkeyPatch, name: str, calls: list[str]) -> None:
    original = getattr(SessionBridgeCoordinator, name)

    async def _wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(name)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(SessionBridgeCoordinator, name, _wrapper)


def _forbid(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    async def _boom(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"misrouted to {name}")

    monkeypatch.setattr(SessionBridgeCoordinator, name, _boom)


def _immediate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exc: type[Exception] = LocalSessionOwnsCanonicalId,
) -> tuple[SessionBridgeCoordinator, _DecliningStore, list[str]]:
    calls: list[str] = []
    _spy(monkeypatch, "_scan_claude_immediate", calls)
    _forbid(monkeypatch, "_scan_claude_persistent")
    coordinator, store = _build(tmp_path, _StatelessDecliningStore, exc)
    return coordinator, store, calls


def _all_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exc: type[Exception] = LocalSessionOwnsCanonicalId,
) -> tuple[SessionBridgeCoordinator, _DecliningStore, list[str]]:
    calls: list[str] = []
    _spy(monkeypatch, "_scan_all_claude_history", calls)
    coordinator, store = _build(tmp_path, _DecliningStore, exc)
    return coordinator, store, calls


def _ran(calls: list[str], name: str, store: _DecliningStore) -> None:
    assert calls == [name], f"expected {name} to run exactly once, got {calls!r}"
    assert store.attempts >= 1, "the store must actually have been asked"


# --------------------------------------------------------------------------
# _scan_all_claude_history
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_history_collision_is_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The path a `scan --all-history` on the production store actually takes.

    `failed` is the assertion that matters: `_scan_all_history_provider` turns
    any nonzero `failed` into `degraded_reason=scan_failed`, and the colliding
    row is never adopted, so before this change the degradation was permanent.
    """

    coordinator, store, calls = _all_history(monkeypatch, tmp_path)

    summary = await coordinator.scan_all_history(Provider.CLAUDE)

    _ran(calls, "_scan_all_claude_history", store)
    assert summary.provider is Provider.CLAUDE
    assert summary.discovered >= 1, "the wrapper's except branch returns discovered=0"
    assert summary.failed == 0, "a collision is benign and must not degrade"
    assert summary.indexed == 0, "nothing was cataloged"
    assert summary.locally_owned >= 1, (
        "the decline must survive to the summary rather than be counted a failure"
    )


@pytest.mark.asyncio
async def test_all_history_collision_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Separate from the summary test: two independent ways to go unnoticed."""

    coordinator, store, calls = _all_history(monkeypatch, tmp_path)

    with caplog.at_level(logging.INFO, logger="session_bridge.coordinator"):
        await coordinator.scan_all_history(Provider.CLAUDE)

    _ran(calls, "_scan_all_claude_history", store)
    messages = [record.getMessage() for record in caplog.records]
    matching = [
        message
        for message in messages
        if "claude_scan_diagnostic" in message
        and "stage=full_history_project" in message
        and "code=claude_local_session_owns_id" in message
    ]
    assert matching, (
        f"the all-history path declined a transcript and logged nothing: {messages!r}"
    )
    assert any("excluded=1" in message for message in matching), (
        f"the diagnostic must carry the count, not just fire: {matching!r}"
    )
    assert not any("codex_scan_diagnostic" in message for message in messages), (
        "the claude decline must not be reported under the codex token"
    )


@pytest.mark.asyncio
async def test_all_history_stale_projection_is_not_counted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The two except clauses must stay SPLIT.

    Re-merging them is invisible to every other test here -- both still
    `continue` -- and would make `locally_owned` OVERSTATE collisions.
    """

    coordinator, store, calls = _all_history(
        monkeypatch, tmp_path, exc=StaleExternalProjection
    )

    summary = await coordinator.scan_all_history(Provider.CLAUDE)

    _ran(calls, "_scan_all_claude_history", store)
    assert summary.failed == 0, "a stale projection is a no-op, not a failure"
    assert summary.indexed == 0
    assert summary.locally_owned == 0, (
        "a stale projection is not a canonical-id collision -- the two except "
        "clauses have been re-merged"
    )


# --------------------------------------------------------------------------
# _scan_claude_immediate
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_immediate_collision_is_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reached only with a state-less store, and proven so rather than assumed."""

    coordinator, store, calls = _immediate(monkeypatch, tmp_path)

    summary = await coordinator.scan_once(Provider.CLAUDE)

    _ran(calls, "_scan_claude_immediate", store)
    assert summary.provider is Provider.CLAUDE
    assert summary.failed == 0, "a collision is benign and must not degrade"
    assert summary.indexed == 0, "nothing was cataloged"
    assert summary.locally_owned >= 1


@pytest.mark.asyncio
async def test_immediate_collision_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator, store, calls = _immediate(monkeypatch, tmp_path)

    with caplog.at_level(logging.INFO, logger="session_bridge.coordinator"):
        await coordinator.scan_once(Provider.CLAUDE)

    _ran(calls, "_scan_claude_immediate", store)
    messages = [record.getMessage() for record in caplog.records]
    matching = [
        message
        for message in messages
        if "claude_scan_diagnostic" in message
        and "stage=immediate_project" in message
        and "code=claude_local_session_owns_id" in message
    ]
    assert matching, (
        f"the immediate path declined a transcript and logged nothing: {messages!r}"
    )
    assert any("excluded=1" in message for message in matching), (
        f"the diagnostic must carry the count, not just fire: {matching!r}"
    )
    assert not any("codex_scan_diagnostic" in message for message in messages), (
        "the claude decline must not be reported under the codex token"
    )


@pytest.mark.asyncio
async def test_immediate_stale_projection_is_not_counted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    coordinator, store, calls = _immediate(
        monkeypatch, tmp_path, exc=StaleExternalProjection
    )

    summary = await coordinator.scan_once(Provider.CLAUDE)

    _ran(calls, "_scan_claude_immediate", store)
    assert summary.failed == 0, "a stale projection is a no-op, not a failure"
    assert summary.indexed == 0
    assert summary.locally_owned == 0, (
        "a stale projection is not a canonical-id collision -- the two except "
        "clauses have been re-merged"
    )
