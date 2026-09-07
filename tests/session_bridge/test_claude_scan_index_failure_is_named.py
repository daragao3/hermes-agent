"""A claude transcript that cannot be indexed must say WHICH one, and why.

All three claude scan paths caught the generic failure as a bare
``except Exception:`` and threw the exception away. The provider-level reporter
added by ``c12e361b3c`` already anticipated this -- its docstring says "Both
``except Exception`` call sites also discarded the exception object entirely, so
even its type was lost" -- but it was never wired to the per-item sites, so the
line it emits reads ``exc=none detail='' tb=()`` and names no transcript.

Why that is not cosmetic. A failure here appends to ``failed_ids``, which
``_merge_native_ids`` rolls into ``remaining_ids`` and ``_save_pending``
re-stages, so ONE transcript that can never be indexed keeps ``failed`` nonzero
on every cycle; ``_scan_provider`` turns any nonzero ``failed`` into
``degraded_reason=scan_failed`` for the whole provider, and
``required_for_service_impact`` is true on that axis. Measured 2026-09-07:
``fae9aa0d-0eb4-4fee-a488-f9be05f7b540`` had no ``sessions`` row and no
``external_sessions`` row at all -- it had never indexed once -- and it held
``session-bridge-service``, ``-catalog`` and ``-continuity`` red for hours.
Finding its id took intersecting the persisted pending set across eight samples,
because nothing in the log named it.

ROUTING TRAP, inherited from ``test_scan_summary_locally_owned_claude_paths``:
``_scan_claude`` dispatches on ``_supports_scan_state(store)``, which duck-types
``get_state``/``set_state``. A fake missing them does not fail, it SELECTS a
different function. So every test asserts which implementation ran by spying on
the coroutine, and forbids the one that must not.

Both directions are pinned. A generic failure must NAME the transcript; a benign
collision and a clean scan must emit no failure diagnostic at all -- otherwise
the fix would trade one unreadable log for a noisier one.
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
)


_MARKER_SECRET = b"synthetic-claude-scan-index-failure-secret"
_NATIVE_ID = "claude-unindexable"
_BOOM = "synthetic upsert refusal"


class _IndexFailure(RuntimeError):
    """Stands in for whatever the real store raises -- the point is the report."""


def _record(native_id: str, index: int) -> bytes:
    return (
        json.dumps(
            {
                "type": "user",
                "sessionId": native_id,
                "uuid": f"{native_id}-{index}",
                "timestamp": "2026-09-07T00:00:0%dZ" % index,
                "message": {"role": "user", "content": f"m{index}"},
            }
        ).encode("utf-8")
        + b"\n"
    )


class _FailingStore:
    """A real store whose every upsert raises, delegating everything else."""

    def __init__(self, inner: SessionBridgeStore, exc: type[Exception]) -> None:
        self._inner = inner
        self._exc = exc
        self.attempts = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def upsert_projection(self, projection: Any, *, rebuild: bool = False) -> Any:
        del rebuild, projection
        self.attempts += 1
        raise self._exc(_BOOM)


class _StatelessFailingStore(_FailingStore):
    """Same, but hiding get_state/set_state -- the only thing that selects
    ``_scan_claude_immediate``."""

    _HIDDEN = frozenset({"get_state", "set_state"})

    def __getattr__(self, name: str) -> Any:
        if name in self._HIDDEN:
            raise AttributeError(name)
        return super().__getattr__(name)


class _CleanStore:
    """Delegates everything; nothing fails. The control."""

    def __init__(self, inner: SessionBridgeStore) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _build(
    tmp_path: Path,
    store: Any,
) -> SessionBridgeCoordinator:
    root = tmp_path / "projects"
    transcript = root / "project" / f"{_NATIVE_ID}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(b"".join(_record(_NATIVE_ID, i) for i in range(3)))
    return SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={
            Provider.CLAUDE: ClaudeSourceAdapter(root, marker_secret=_MARKER_SECRET)
        },
    )


def _inner(tmp_path: Path) -> SessionBridgeStore:
    return SessionBridgeStore(SessionDB(db_path=tmp_path / "state.db"), clock=lambda: 1_000.0)


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


def _failures(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        message
        for message in (record.getMessage() for record in caplog.records)
        if "provider_scan_diagnostic" in message and "provider=claude" in message
    ]


def _assert_names_the_transcript(messages: list[str], stage: str) -> None:
    matching = [
        message
        for message in messages
        if f"stage={stage}" in message and "code=claude_scan_failed" in message
    ]
    assert matching, f"no claude failure diagnostic for stage={stage}: {messages!r}"
    assert any(f"native={_NATIVE_ID}" in message for message in matching), (
        f"the diagnostic must NAME the transcript, not just fire: {matching!r}"
    )
    assert any("exc=_IndexFailure" in message for message in matching), (
        f"the exception type must survive the clause: {matching!r}"
    )
    assert any(_BOOM in message for message in matching), (
        f"the exception message must survive the clause: {matching!r}"
    )
    assert not any("exc=none" in message for message in matching), (
        "exc=none is the pre-fix shape and means the clause still discarded it"
    )


# --------------------------------------------------------------------------
# fires -- one per claude scan path
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persistent_index_failure_names_the_transcript(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The live dispatch path -- this is the one that was red in production."""

    calls: list[str] = []
    _spy(monkeypatch, "_scan_claude_persistent", calls)
    _forbid(monkeypatch, "_scan_claude_immediate")
    store = _FailingStore(_inner(tmp_path), _IndexFailure)
    coordinator = _build(tmp_path, store)

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CLAUDE)

    assert calls == ["_scan_claude_persistent"], calls
    assert store.attempts >= 1, "the store must actually have been asked"
    assert summary.failed >= 1, "the failure itself is unchanged; only the report is new"
    _assert_names_the_transcript(_failures(caplog), "persistent_project")


@pytest.mark.asyncio
async def test_immediate_index_failure_names_the_transcript(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    _spy(monkeypatch, "_scan_claude_immediate", calls)
    _forbid(monkeypatch, "_scan_claude_persistent")
    store = _StatelessFailingStore(_inner(tmp_path), _IndexFailure)
    coordinator = _build(tmp_path, store)

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        await coordinator.scan_once(Provider.CLAUDE)

    assert calls == ["_scan_claude_immediate"], calls
    assert store.attempts >= 1
    _assert_names_the_transcript(_failures(caplog), "immediate_project")


@pytest.mark.asyncio
async def test_all_history_index_failure_names_the_transcript(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    _spy(monkeypatch, "_scan_all_claude_history", calls)
    store = _FailingStore(_inner(tmp_path), _IndexFailure)
    coordinator = _build(tmp_path, store)

    with caplog.at_level(logging.WARNING, logger="session_bridge.coordinator"):
        await coordinator.scan_all_history(Provider.CLAUDE)

    assert calls == ["_scan_all_claude_history"], calls
    assert store.attempts >= 1
    _assert_names_the_transcript(_failures(caplog), "full_history_project")


# --------------------------------------------------------------------------
# stays quiet -- otherwise the fix just trades one unreadable log for another
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_benign_collision_emits_no_failure_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The split that 2026-09-03 established must survive this change.

    A canonical-id collision is deliberately NOT a failure. It has its own
    INFO-level ``claude_scan_diagnostic``; it must not also start appearing as a
    ``provider_scan_diagnostic``, or the new line would fire continuously on a
    box where the collision is permanent -- which is exactly this box.
    """

    calls: list[str] = []
    _spy(monkeypatch, "_scan_claude_persistent", calls)
    store = _FailingStore(_inner(tmp_path), LocalSessionOwnsCanonicalId)
    coordinator = _build(tmp_path, store)

    with caplog.at_level(logging.INFO, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CLAUDE)

    assert calls == ["_scan_claude_persistent"], calls
    assert store.attempts >= 1
    assert summary.failed == 0, "a collision is benign and must not degrade"
    assert summary.locally_owned >= 1
    assert not _failures(caplog), (
        f"a benign collision must not emit a failure diagnostic: {_failures(caplog)!r}"
    )


@pytest.mark.asyncio
async def test_a_clean_scan_emits_no_failure_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The control: nothing fails, so nothing is reported."""

    calls: list[str] = []
    _spy(monkeypatch, "_scan_claude_persistent", calls)
    coordinator = _build(tmp_path, _CleanStore(_inner(tmp_path)))

    with caplog.at_level(logging.INFO, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CLAUDE)

    assert calls == ["_scan_claude_persistent"], calls
    assert summary.failed == 0
    assert summary.indexed >= 1, (
        "if nothing indexed, this control is vacuous -- it would pass on a scan "
        "that never reached the store at all"
    )
    assert not _failures(caplog), (
        f"a clean scan must stay silent: {_failures(caplog)!r}"
    )


def test_existing_call_sites_keep_working_without_a_native_id() -> None:
    """`native_id` is optional, so the provider-level sites are unchanged."""

    from session_bridge.coordinator import _safe_native_token

    assert _safe_native_token(None) == ""
    assert _safe_native_token(_NATIVE_ID) == _NATIVE_ID
    # A stem that could break the log line into misreadable pieces is stripped,
    # and an absurd one is bounded.
    assert " " not in _safe_native_token("a b'c\"d e=f")
    assert len(_safe_native_token("x" * 500)) == 64
