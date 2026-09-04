"""IdleChipArchiveWorker: the scheduled-task fire axis.

Every scheduled-task fire leaves a ``scheduledTaskId`` registry record that
never exits, and until this axis existed nothing retired it: measured
2026-09-02 over the live convergence store, ``_is_chip()`` was False on 7/7
unarchived task records (noun-first titles derived from the taskId, cwd a repo
root, so neither chip branch matched) while all 7 carried
``bypassPermissions``. One task on a ``15 1,4,7,10,13,16,19,22 * * *`` cron is
eight stranded records a day; ``fifa-kickoff`` reached 78 before a one-off hand
sweep on 2026-08-23 cleared them.

The axis is OFF unless a caller passes ``task_idle_seconds``, and it carries its
OWN window: a cron firing eight times a day stacks eight records inside a single
24h chip window, so the window has to say "this fire is over", not "this chip is
stale".
"""
from __future__ import annotations

import json
import os
from datetime import timezone
from pathlib import Path

import pytest

from session_bridge.mirror_float import (
    CaptureMissRecorder,
    IdleChipArchiveWorker,
    default_capture_miss_log_path,
    read_open_claim_session_ids,
)
from tests.session_bridge.test_idle_chip_archive import (
    DAY,
    NOW,
    _load,
    _serve_runtime_coordinator,
    _worker,
    _write_record,
)


def _write_task_record(
    root: Path,
    session_id: str,
    *,
    scheduled_task_id: str = "capone-82a8fdc9-fix1-review-adjudication",
    extra: dict | None = None,
    **overrides,
) -> Path:
    """A record shaped like a real scheduled-task fire.

    Deliberately noun-first with a repo-root cwd, i.e. invisible to BOTH chip
    branches — a verb title here would let these tests pass for the wrong reason.
    """
    options = {
        "title": "Capone 82a8fdc9 fix1 review adjudication",
        "cwd": "C:/Users/diego/.hermes/services/jobflow-platform",
    }
    options.update(overrides)
    path = _write_record(root, session_id, **options)
    record = _load(path)
    record["scheduledTaskId"] = scheduled_task_id
    record.update(extra or {})
    path.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
    stamp = options.get("mtime") or NOW - 2 * DAY
    os.utime(path, (stamp, stamp))
    return path


# --- the gap itself ----------------------------------------------------------


def test_task_record_is_invisible_to_both_chip_branches() -> None:
    record = {
        "title": "Capone 82a8fdc9 fix1 review adjudication",
        "cwd": "C:/Users/diego/.hermes/services/jobflow-platform",
        "originCwd": "C:/Users/diego/.hermes/services/jobflow-platform",
        "permissionMode": "bypassPermissions",
        "scheduledTaskId": "capone-82a8fdc9-fix1-review-adjudication",
    }
    assert IdleChipArchiveWorker._is_chip(record) is False
    assert IdleChipArchiveWorker._record_kind(record, task_axis=False) is None
    assert IdleChipArchiveWorker._record_kind(record, task_axis=True) == "task"


def test_task_records_untouched_when_axis_is_off(tmp_path) -> None:
    path = _write_task_record(tmp_path / "a", "task1")
    worker = _worker(tmp_path / "a")  # task_idle_seconds defaults to None

    assert worker.run_once()["archived"] == 0
    assert _load(path)["isArchived"] is False


def test_archives_idle_task_record_when_axis_armed(tmp_path) -> None:
    path = _write_task_record(tmp_path / "a", "task1")
    worker = _worker(tmp_path / "a", task_idle_seconds=4 * 3600.0)

    assert worker.run_once()["archived"] == 1
    archived = _load(path)
    assert archived["isArchived"] is True
    # Nothing else moves: byte-equivalent apart from the flag.
    assert archived["scheduledTaskId"] == "capone-82a8fdc9-fix1-review-adjudication"
    assert archived["extraField"] == {"must": "survive"}


# --- the separate window is the point ----------------------------------------


def test_task_record_uses_its_own_window_not_the_chip_one(tmp_path) -> None:
    """Both records are 6h idle; chip window 24h, task window 4h."""
    six_hours_ago = int((NOW - 6 * 3600) * 1000)
    chip = _write_record(tmp_path / "a", "chip1", last_activity_at_ms=six_hours_ago)
    task = _write_task_record(
        tmp_path / "a", "task1", last_activity_at_ms=six_hours_ago
    )
    worker = _worker(tmp_path / "a", idle_seconds=DAY, task_idle_seconds=4 * 3600.0)

    worker.run_once()

    assert _load(chip)["isArchived"] is False
    assert _load(task)["isArchived"] is True


def test_task_record_still_live_inside_its_window_is_spared(tmp_path) -> None:
    path = _write_task_record(
        tmp_path / "a", "task1", last_activity_at_ms=int((NOW - 3600) * 1000)
    )
    worker = _worker(tmp_path / "a", task_idle_seconds=4 * 3600.0)

    assert worker.run_once()["archived"] == 0
    assert _load(path)["isArchived"] is False


def test_task_liveness_spans_every_store_copy(tmp_path) -> None:
    """A stale union-synced copy must not authorize archiving a live fire.

    This is the check whose absence archived 16 live sessions on 2026-08-24;
    the task axis inherits it rather than reimplementing it.
    """
    stale = _write_task_record(tmp_path / "a", "task1")
    fresh = _write_task_record(
        tmp_path / "b", "task1", last_activity_at_ms=int((NOW - 60) * 1000)
    )
    worker = _worker(tmp_path / "a", tmp_path / "b", task_idle_seconds=4 * 3600.0)

    assert worker.run_once()["archived"] == 0
    assert _load(stale)["isArchived"] is False
    assert _load(fresh)["isArchived"] is False


# --- records that must stay visible ------------------------------------------


def test_errored_records_are_never_archived(tmp_path) -> None:
    """An errored fire may have ended blocked or without capture."""
    task = _write_task_record(
        tmp_path / "a",
        "task1",
        extra={"error": "Session ended unexpectedly", "errorAt": 1},
    )
    chip = _write_record(tmp_path / "a", "chip1")
    record = _load(chip)
    record["error"] = "Session ended unexpectedly"
    chip.write_text(json.dumps(record), encoding="utf-8")
    os.utime(chip, (NOW - 2 * DAY, NOW - 2 * DAY))

    worker = _worker(tmp_path / "a", task_idle_seconds=4 * 3600.0)

    assert worker.run_once()["archived"] == 0
    assert _load(task)["isArchived"] is False
    assert _load(chip)["isArchived"] is False


def test_mirror_and_non_bypass_task_records_are_still_excluded() -> None:
    mirror = {
        "title": "[Codex] Capone review",
        "permissionMode": "bypassPermissions",
        "scheduledTaskId": "t",
    }
    typed = {
        "title": "Capone review",
        "permissionMode": "acceptEdits",
        "scheduledTaskId": "t",
    }
    assert IdleChipArchiveWorker._record_kind(mirror, task_axis=True) is None
    assert IdleChipArchiveWorker._record_kind(typed, task_axis=True) is None


def test_blank_or_non_string_scheduled_task_id_is_not_a_task() -> None:
    for value in ("", "   ", None, 5, True):
        record = {
            "title": "Capone review",
            "cwd": "C:\\Users\\diego",
            "permissionMode": "bypassPermissions",
            "scheduledTaskId": value,
        }
        assert IdleChipArchiveWorker._record_kind(record, task_axis=True) is None


# --- the disabled axis must not narrow what already worked -------------------


def test_disabled_axis_does_not_narrow_chip_coverage(tmp_path) -> None:
    """A verb-titled task record stays chip-archivable while the axis is OFF.

    Real taskIds do produce verb-first titles (``check-329-kill-row-verdict``).
    If the disabled axis claimed them, adding it would SHRINK what gets archived.
    """
    path = _write_task_record(
        tmp_path / "a",
        "task1",
        scheduled_task_id="check-329-kill-row-verdict",
        title="Check 329 kill row verdict",
        cwd="C:\\Users\\diego",
    )
    worker = _worker(tmp_path / "a")

    assert worker.run_once()["archived"] == 1
    assert _load(path)["isArchived"] is True


def test_task_wins_over_chip_when_axis_armed() -> None:
    record = {
        "title": "Check 329 kill row verdict",
        "cwd": "C:\\Users\\diego",
        "permissionMode": "bypassPermissions",
        "scheduledTaskId": "check-329-kill-row-verdict",
    }
    assert IdleChipArchiveWorker._record_kind(record, task_axis=True) == "task"
    assert IdleChipArchiveWorker._record_kind(record, task_axis=False) == "chip"


# --- open loops claims -------------------------------------------------------


def _claims_file(tmp_path: Path, rows: object) -> Path:
    path = tmp_path / "claims.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_reads_open_ccd_claim_holders(tmp_path) -> None:
    path = _claims_file(
        tmp_path,
        [
            {
                "id": "open-one",
                "status": "active",
                "holders": [
                    {"session": "ccd:local_aaa"},
                    # A pid holder names no session: dead by the time anyone
                    # reads it, and the number gets reused.
                    {"session": "pid:32016"},
                ],
            },
            {
                "id": "finished",
                "status": "done",
                "holders": [{"session": "ccd:local_bbb"}],
            },
            {"id": "no-holders", "status": "active"},
        ],
    )

    assert read_open_claim_session_ids(path) == frozenset({"local_aaa"})


def test_unreadable_registry_reads_as_none_not_empty(tmp_path) -> None:
    """None means "could not read", which is NOT "no claims" — loops exit 4."""
    assert read_open_claim_session_ids(tmp_path / "absent.json") is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert read_open_claim_session_ids(broken) is None

    # Valid JSON of the wrong shape is just as unreadable as broken JSON.
    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text('{"claims": []}', encoding="utf-8")
    assert read_open_claim_session_ids(wrong_shape) is None


def test_task_record_with_an_open_claim_is_never_archived(tmp_path) -> None:
    held = _write_task_record(tmp_path / "a", "held")
    free = _write_task_record(
        tmp_path / "a", "free", scheduled_task_id="some-other-task"
    )
    worker = _worker(
        tmp_path / "a",
        task_idle_seconds=4 * 3600.0,
        open_claim_session_ids=lambda: frozenset({"local_held"}),
    )

    assert worker.run_once()["archived"] == 1
    assert _load(held)["isArchived"] is False
    assert _load(free)["isArchived"] is True


def test_unreadable_registry_stands_the_task_axis_down(tmp_path) -> None:
    """Degrade to the status quo, never past it."""
    task = _write_task_record(tmp_path / "a", "task1")
    chip = _write_record(tmp_path / "a", "chip1")
    worker = _worker(
        tmp_path / "a",
        task_idle_seconds=4 * 3600.0,
        open_claim_session_ids=lambda: None,
    )

    assert worker.run_once()["archived"] == 1
    assert _load(task)["isArchived"] is False
    # The CHIP lane is untouched by an unreadable registry on purpose: making it
    # fail closed on a file documented to VANISH here would silently stop
    # archiving that already works.
    assert _load(chip)["isArchived"] is True


def test_claim_guard_is_inert_when_no_reader_is_supplied(tmp_path) -> None:
    path = _write_task_record(tmp_path / "a", "task1")
    worker = _worker(tmp_path / "a", task_idle_seconds=4 * 3600.0)

    assert worker.run_once()["archived"] == 1
    assert _load(path)["isArchived"] is True


# --- construction ------------------------------------------------------------


def test_rejects_invalid_task_idle_seconds() -> None:
    with pytest.raises(ValueError, match="task_idle_seconds"):
        IdleChipArchiveWorker(registry_roots=(), task_idle_seconds=0.0)
    with pytest.raises(ValueError, match="task_idle_seconds"):
        IdleChipArchiveWorker(registry_roots=(), task_idle_seconds=float("inf"))


def test_lookback_relation_is_checked_against_the_widest_window() -> None:
    """A task window wider than half the lookback ages records out unseen."""
    with pytest.raises(ValueError, match="lookback"):
        IdleChipArchiveWorker(
            registry_roots=(),
            idle_seconds=DAY,
            task_idle_seconds=10 * DAY,
            lookback_seconds=5 * DAY,
        )
    IdleChipArchiveWorker(
        registry_roots=(),
        idle_seconds=DAY,
        task_idle_seconds=4 * 3600.0,
        lookback_seconds=14 * DAY,
    )


# --- config plumbing ---------------------------------------------------------


def test_config_parses_idle_task_session_archive_seconds(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from session_bridge.config import BridgeConfig

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {
            "session_bridge": {
                "claude_visibility": {
                    "enabled": True,
                    "archive_idle_chips": True,
                    "idle_task_session_archive_seconds": 14_400,
                }
            }
        },
    )
    config = BridgeConfig.load(path=tmp_path / "session_bridge.toml")
    assert config.claude_visibility.idle_task_session_archive_seconds == 14_400


def test_config_task_archive_seconds_defaults_off_and_rejects_bad_values(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from session_bridge.config import BridgeConfig

    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"session_bridge": {}})
    defaults = BridgeConfig.load(path=tmp_path / "session_bridge.toml")
    assert defaults.claude_visibility.idle_task_session_archive_seconds is None

    # An explicit null is the documented way to say OFF and must not raise.
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {
            "session_bridge": {
                "claude_visibility": {"idle_task_session_archive_seconds": None}
            }
        },
    )
    explicit_off = BridgeConfig.load(path=tmp_path / "session_bridge.toml")
    assert explicit_off.claude_visibility.idle_task_session_archive_seconds is None

    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {
            "session_bridge": {
                "claude_visibility": {"idle_task_session_archive_seconds": 60}
            }
        },
    )
    with pytest.raises(ValueError, match="idle_task_session_archive_seconds"):
        BridgeConfig.load(path=tmp_path / "session_bridge.toml")


# --- serve wiring ------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    from hermes_state import SessionDB

    database = SessionDB(tmp_path / "state.db")
    try:
        yield database
    finally:
        database.close()


def test_serve_runtime_passes_task_window_through(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from session_bridge.catalog import UnifiedCatalog
    from session_bridge.cli import ProductionBackend
    from session_bridge.config import BridgeConfig, ClaudeVisibilityConfig
    from session_bridge.models import Provider
    from session_bridge.store import SessionBridgeStore

    monkeypatch.setattr(
        "session_bridge.cli.discover_ccd_convergence_roots",
        lambda: (Path("C:/sentinel-registry"),),
    )
    store = SessionBridgeStore(db, clock=lambda: 100.0, local_timezone=timezone.utc)
    backend = ProductionBackend(
        replace(
            BridgeConfig(),
            claude_visibility=replace(
                ClaudeVisibilityConfig(),
                enabled=True,
                archive_idle_chips=True,
                idle_task_session_archive_seconds=14_400,
            ),
        )
    )
    backend._db = db
    backend._store = store
    backend._catalog = UnifiedCatalog(db, store)
    monkeypatch.setattr("session_bridge.cli.resolve_marker_key", lambda: b"k" * 32)
    monkeypatch.setattr(
        "session_bridge.cli.resolve_cli_executable", lambda name: (name,)
    )
    coordinator = backend._provider_runtime(
        targets=False, catalog_only=False, providers=(Provider.CLAUDE,)
    )

    assert coordinator._idle_chip_archiver._task_idle_seconds == 14_400.0
    # And the claim reader is wired, not left None — otherwise the open-claim
    # guard would be dead code in production while its unit tests stayed green.
    assert coordinator._idle_chip_archiver._open_claim_session_ids is not None
    assert isinstance(
        coordinator._idle_chip_archiver._open_claim_session_ids(),
        (frozenset, type(None)),
    )
    # Same reasoning for the capture observer: unit-tested in isolation, it
    # would still report nothing in production if serve never passed one.
    observer = coordinator._idle_chip_archiver._capture_observer
    assert isinstance(observer, CaptureMissRecorder)
    assert observer._log_path == default_capture_miss_log_path()


def test_serve_runtime_leaves_task_axis_off_by_default(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "session_bridge.cli.discover_ccd_convergence_roots",
        lambda: (Path("C:/sentinel-registry"),),
    )
    coordinator = _serve_runtime_coordinator(db, monkeypatch, archive_idle_chips=True)
    assert coordinator._idle_chip_archiver._task_idle_seconds is None
