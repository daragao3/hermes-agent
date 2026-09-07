"""A transcript whose origin cannot be decided is unadoptable, not a scan failure.

``_detect_origin`` raises when two different bridge ids authenticate inside one
claude transcript. Until 2026-09-07 that was a bare ``ValueError``, so nothing
could catch it narrowly and it fell to the scan paths' generic handler -- and
because a failure re-stages the transcript (``failed_ids`` -> ``remaining_ids``
-> ``_save_pending``), ONE such transcript kept ``failed`` nonzero on every
cycle. ``_scan_provider`` turns any nonzero ``failed`` into
``degraded_reason=scan_failed`` for the whole provider, on an axis carrying
``required_for_service_impact=true``, so ``session-bridge-service``, ``-catalog``
and ``-continuity`` were red for hours on 2026-09-07 and a restart did not clear
it. The culprit was ``fae9aa0d-0eb4-4fee-a488-f9be05f7b540``.

WHY SKIPPING IS THE RIGHT CALL RATHER THAN RECLASSIFYING. ``_detect_origin``
harvests markers from the text of ANY user or assistant record, so a session that
merely PRINTS marker strings collects them as if they were its own provenance --
and on this machine agent sessions work on the bridge constantly. Measured on
that transcript: three distinct marker strings, two first appearing in record 1
and one first appearing in record 356. A mid-conversation first appearance is the
signature of a transcript that DISPLAYED a marker, since a genuine continuation
stamps its marker at the start. But origin is HMAC-authenticated provenance
feeding the visibility and registration lanes, and that evidence does not
actually settle which reading is true -- so this skips the transcript (leaving it
exactly as unindexed as it already was) instead of deciding it is native.

Both directions are pinned: a conflict must stop degrading the provider AND must
still be reported, and an ordinary index failure must still degrade, or this
change would have quietly disarmed the failure path it is narrowing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from hermes_state import SessionDB
from session_bridge.claude_adapter import (
    ClaudeSourceAdapter,
    ConflictingClaudeBridgeMarkers,
)
from session_bridge.config import BridgeConfig
from session_bridge.coordinator import SessionBridgeCoordinator
from session_bridge.models import Provider
from session_bridge.store import SessionBridgeStore


_MARKER_SECRET = b"synthetic-conflicting-markers-secret"
_NATIVE_ID = "claude-conflicting-markers"


class _IndexFailure(RuntimeError):
    """An ordinary index failure -- the control that must STILL degrade."""


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


class _RaisingAdapter(ClaudeSourceAdapter):
    """Raise from `parse`, where `_detect_origin` raises in production."""

    def __init__(self, *args: Any, exc: BaseException, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._exc = exc
        self.parses = 0

    def parse(self, path: Path, previous: Any = None) -> Any:
        self.parses += 1
        raise self._exc


def _build(tmp_path: Path, exc: BaseException) -> tuple[SessionBridgeCoordinator, Any]:
    root = tmp_path / "projects"
    transcript = root / "project" / f"{_NATIVE_ID}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(b"".join(_record(_NATIVE_ID, i) for i in range(3)))
    store = SessionBridgeStore(SessionDB(db_path=tmp_path / "state.db"), clock=lambda: 1_000.0)
    adapter = _RaisingAdapter(root, marker_secret=_MARKER_SECRET, exc=exc)
    coordinator = SessionBridgeCoordinator(
        config=BridgeConfig(),
        store=store,
        adapters={Provider.CLAUDE: adapter},
    )
    return coordinator, adapter


@pytest.mark.asyncio
async def test_a_marker_conflict_does_not_degrade_the_provider(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The whole point: `failed` stays 0, so scan_failed never latches."""

    coordinator, adapter = _build(
        tmp_path, ConflictingClaudeBridgeMarkers(("bridge-a", "bridge-b"))
    )

    with caplog.at_level(logging.INFO, logger="session_bridge.coordinator"):
        summary = await coordinator.scan_once(Provider.CLAUDE)

    assert adapter.parses >= 1, "the adapter must actually have been asked to parse"
    assert summary.failed == 0, (
        "an undecidable origin is unadoptable, not a scan failure -- nonzero "
        "`failed` is what latches degraded_reason=scan_failed on the provider"
    )
    assert summary.indexed == 0, "it is still not cataloged; only the verdict changed"


@pytest.mark.asyncio
async def test_a_marker_conflict_is_still_reported(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Counted, never silent -- otherwise this trades a red row for a blind spot."""

    coordinator, _ = _build(
        tmp_path, ConflictingClaudeBridgeMarkers(("bridge-a", "bridge-b"))
    )

    with caplog.at_level(logging.INFO, logger="session_bridge.coordinator"):
        await coordinator.scan_once(Provider.CLAUDE)

    messages = [record.getMessage() for record in caplog.records]
    matching = [
        message
        for message in messages
        if "claude_scan_diagnostic" in message
        and "code=claude_conflicting_bridge_markers" in message
    ]
    assert matching, f"the skip must be reported, not silent: {messages!r}"
    assert any("skipped=1" in message for message in matching), (
        f"the diagnostic must carry the count: {matching!r}"
    )
    assert any(_NATIVE_ID in message for message in matching), (
        f"and it must NAME the transcript, or the operator cannot act: {matching!r}"
    )


@pytest.mark.asyncio
async def test_an_ordinary_index_failure_still_degrades(
    tmp_path: Path,
) -> None:
    """The control. Without this, narrowing the clause could disarm the whole
    failure path and every one of these tests would still pass."""

    coordinator, adapter = _build(tmp_path, _IndexFailure("boom"))

    summary = await coordinator.scan_once(Provider.CLAUDE)

    assert adapter.parses >= 1
    assert summary.failed >= 1, (
        "only the marker conflict is exempt; a genuine failure must still count"
    )


def test_the_exception_stays_a_valueerror_with_the_same_message() -> None:
    """Existing callers and tests match on ValueError and on the text."""

    exc = ConflictingClaudeBridgeMarkers(("a", "b"))
    assert isinstance(exc, ValueError)
    assert str(exc) == "Claude transcript has conflicting bridge markers"
    assert exc.bridge_ids == ("a", "b")
