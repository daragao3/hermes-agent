"""`locally_owned` on the CLAUDE persistent scan path.

The 2026-09-01 change (7c72d3e2a9) added the ScanSummary field and wired all
three CODEX paths plus the two wrapper passthroughs. The CLAUDE persistent path
got the counter and the final-return wiring, but was left with NO log block at
all -- the three codex paths each emit one. So a claude-side canonical-id
collision reached the summary while leaving no trace an operator reading the log
could find, and nothing in the suite pinned the claude wiring either: every test
in `test_scan_summary_locally_owned.py` drives `Provider.CODEX`.

There are 335 claude `sessions` rows with no `external_sessions` row (all
rowid<=3523, the same pre-catalog cutover that stranded the codex backlog), so
this counter is non-zero in production.

ROUTING. `_scan_claude` dispatches on `_supports_scan_state(store)`, which
duck-types `get_state`/`set_state`; a fake missing them routes silently to
`_scan_claude_immediate` -- a DIFFERENT function, with no counter at all -- and
an under-implemented fake does not fail, it selects the other branch (measured
on the codex twin, 48c918c0e4). These tests therefore wrap a REAL
`SessionBridgeStore` and prove the route independently of the log, by asserting
the persistent path's state keys were written: `_scan_claude_immediate` writes
no state.
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


_MARKER_SECRET = b"synthetic-locally-owned-claude-secret"
_CLAUDE_STATE_KEYS = (
    "session-bridge:scan:claude:staged-fingerprints",
    "session-bridge:scan:claude:fingerprints",
)


def _record(native_id: str, index: int) -> bytes:
    return (
        json.dumps(
            {
                "type": "user",
                "sessionId": native_id,
                "uuid": f"event-{native_id}-{index:04d}",
                "timestamp": f"2026-09-02T10:00:{index % 60:02d}Z",
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
    """A real store whose every upsert collides, delegating everything else.

    Delegation is the point: `get_state`/`set_state` reach the real
    `SessionBridgeStore`, so `_supports_scan_state` is True and the coordinator
    routes to `_scan_claude_persistent`. `__getattr__` also keeps the fake from
    drifting as the store grows methods.
    """

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


def _build(
    tmp_path: Path,
    exc: type[Exception] = LocalSessionOwnsCanonicalId,
) -> tuple[SessionBridgeCoordinator, _DecliningStore]:
    root = tmp_path / "projects"
    transcript = root / "project" / "claude-collision.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(b"".join(_record("claude-collision", i) for i in range(3)))
    db = SessionDB(db_path=tmp_path / "state.db")
    store = _DecliningStore(SessionBridgeStore(db, clock=lambda: 1_000.0), exc)
    coordinator = SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={
            Provider.CLAUDE: ClaudeSourceAdapter(root, marker_secret=_MARKER_SECRET)
        },
    )
    return coordinator, store


def _assert_took_the_persistent_path(store: _DecliningStore) -> None:
    """Independent of the log block, so a log regression cannot mask a misroute."""

    assert store.attempts >= 1, "the store must actually have been asked"
    written = [key for key in _CLAUDE_STATE_KEYS if store.get_state(key) is not None]
    assert written, (
        "no claude scan state was written: this ran _scan_claude_immediate, "
        "which has no locally_owned counter at all -- the assertions below "
        "would be made against the wrong function"
    )


@pytest.mark.asyncio
async def test_claude_collision_survives_to_the_scan_summary(tmp_path: Path) -> None:
    """The final return of `_scan_claude_persistent` must carry the counter.

    That return is the one a healthy bridge takes every cycle. Dropping the
    field there is silent: the caller sees discovered>=1, indexed=0, failed=0
    and cannot tell a clean no-op scan from one that declined everything.
    """

    coordinator, store = _build(tmp_path)

    summary = await coordinator.scan_once(Provider.CLAUDE)

    _assert_took_the_persistent_path(store)
    assert summary.provider is Provider.CLAUDE
    assert summary.failed == 0, "a collision is benign and must not degrade"
    assert summary.indexed == 0, "nothing was cataloged"
    assert summary.locally_owned >= 1, (
        "the claude decline must survive to the summary; this is the whole point"
    )


@pytest.mark.asyncio
async def test_claude_collision_is_logged(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Counted, never silent -- the rule the three codex paths already follow.

    Deliberately separate from the summary test: the summary field and the
    diagnostic are two independent ways for a claude decline to go unnoticed,
    and one assertion covering both cannot say which broke.
    """

    coordinator, store = _build(tmp_path)

    with caplog.at_level(logging.INFO, logger="session_bridge.coordinator"):
        await coordinator.scan_once(Provider.CLAUDE)

    _assert_took_the_persistent_path(store)
    messages = [record.getMessage() for record in caplog.records]
    matching = [
        message
        for message in messages
        if "claude_scan_diagnostic" in message
        and "code=claude_local_session_owns_id" in message
    ]
    assert matching, (
        "the claude persistent path declined a transcript and logged nothing: "
        f"records={messages!r}"
    )
    assert any("excluded=1" in message for message in matching), (
        f"the diagnostic must carry the count, not just fire: {matching!r}"
    )
    assert not any("codex_scan_diagnostic" in message for message in messages), (
        "the claude decline must not be reported under the codex token"
    )


@pytest.mark.asyncio
async def test_claude_stale_projection_is_not_counted_as_locally_owned(
    tmp_path: Path,
) -> None:
    """The two except clauses have identical bodies but must stay SPLIT.

    Until 2026-09-01 this path caught
    `(LocalSessionOwnsCanonicalId, StaleExternalProjection)` in one clause.
    Re-merging them is invisible to every other test -- both still `continue`,
    claude retry semantics unchanged -- and would make the new field OVERSTATE
    collisions by folding stale projections in. This is the behavioural check;
    the codex twin file asserts on the source text.
    """

    coordinator, store = _build(tmp_path, exc=StaleExternalProjection)

    summary = await coordinator.scan_once(Provider.CLAUDE)

    _assert_took_the_persistent_path(store)
    assert summary.failed == 0, "a stale projection is a no-op, not a failure"
    assert summary.indexed == 0
    assert summary.locally_owned == 0, (
        "a stale projection is not a canonical-id collision and must not be "
        "counted as one -- the two except clauses have been re-merged"
    )
