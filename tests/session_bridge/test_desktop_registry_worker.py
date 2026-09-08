from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hermes_state import SessionDB
from session_bridge.desktop_registry import RegistryScanError
from session_bridge.desktop_registry_worker import (
    WORKER_HEARTBEAT_STATE_KEY,
    DesktopRegistrySyncWorker,
)
from session_bridge.store import SessionBridgeStore


@pytest.fixture
def db(tmp_path):
    database = SessionDB(tmp_path / "state.db")
    yield database
    database.close()


@pytest.fixture
def store(db):
    return SessionBridgeStore(db, clock=lambda: 100.0)


def _write_record(root: Path, session_id: str, *, mtime_ns: int, **fields) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{session_id}.json"
    record = {
        "sessionId": session_id,
        "title": "Original",
        "isArchived": False,
        **fields,
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    return tuple(tmp_path / name for name in ("a", "b", "c"))


def _worker(store, roots) -> DesktopRegistrySyncWorker:
    return DesktopRegistrySyncWorker(
        store,
        registry_roots=roots,
        run_min_interval_seconds=0.0,
    )


def _read(root: Path, session_id: str) -> dict:
    return json.loads((root / f"{session_id}.json").read_text(encoding="utf-8"))


def test_first_cycle_bootstraps_converges_and_persists_baselines(
    tmp_path, store
) -> None:
    a, b, c = _roots(tmp_path)
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Newest")
    _write_record(c, "local_one", mtime_ns=200, title="Middle")

    worker = _worker(store, (a, b, c))
    counters = worker.run_once()

    assert counters["patched"] == 2
    assert counters["raced"] == 0
    assert counters["scan_failed"] == 0
    for root in (a, b, c):
        assert _read(root, "local_one")["title"] == "Newest"
    baselines = store.load_desktop_registry_baselines()
    assert baselines
    assert store.pending_desktop_registry_run() is None

    second = worker.run_once()
    assert second["patched"] == 0
    assert second["baseline_rows_advanced"] == 0


def test_manual_archive_and_unarchive_propagate_between_cycles(
    tmp_path, store
) -> None:
    a, b, c = _roots(tmp_path)
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100)
    worker = _worker(store, (a, b, c))
    worker.run_once()

    path = b / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["isArchived"] = True
    path.write_text(json.dumps(record), encoding="utf-8")

    counters = worker.run_once()
    assert counters["patched"] == 2
    assert all(_read(root, "local_one")["isArchived"] is True for root in (a, b, c))

    path = c / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["isArchived"] = False
    path.write_text(json.dumps(record), encoding="utf-8")

    counters = worker.run_once()
    assert counters["patched"] == 2
    assert all(_read(root, "local_one")["isArchived"] is False for root in (a, b, c))


def test_missing_replica_is_created_from_composite(tmp_path, store) -> None:
    a, b, c = _roots(tmp_path)
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Newest")
    c.mkdir()

    counters = _worker(store, (a, b, c)).run_once()

    assert counters["created"] == 1
    assert _read(c, "local_one")["title"] == "Newest"


def test_pending_run_is_abandoned_then_replanned(tmp_path, store) -> None:
    a, b, c = _roots(tmp_path)
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Newest")
    _write_record(c, "local_one", mtime_ns=200, title="Middle")
    store.stage_desktop_registry_run("stale-run", 1, '{"mutations": []}')

    counters = _worker(store, (a, b, c)).run_once()

    assert counters["recovered_runs"] == 1
    assert counters["patched"] == 2
    assert store.pending_desktop_registry_run() is None
    for root in (a, b, c):
        assert _read(root, "local_one")["title"] == "Newest"


def test_scan_error_fails_closed_without_writes(tmp_path, store) -> None:
    a, b, c = _roots(tmp_path)
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Newest")
    c.mkdir()
    (c / "local_bad.json").write_text("{not json", encoding="utf-8")
    before = (a / "local_one.json").read_bytes()

    counters = _worker(store, (a, b, c)).run_once()

    assert counters["scan_failed"] == 1
    assert counters["patched"] == 0
    assert (a / "local_one.json").read_bytes() == before
    assert store.load_desktop_registry_baselines() == []


def test_protected_divergence_is_recorded_and_never_patched(
    tmp_path, store, db
) -> None:
    a, b, c = _roots(tmp_path)
    _write_record(a, "local_one", mtime_ns=100, cliSessionId="cli-a")
    _write_record(b, "local_one", mtime_ns=300, cliSessionId="cli-b")
    _write_record(c, "local_one", mtime_ns=200, cliSessionId="cli-a")

    counters = _worker(store, (a, b, c)).run_once()

    assert counters["conflicts"] == 1
    assert _read(a, "local_one")["cliSessionId"] == "cli-a"
    assert _read(b, "local_one")["cliSessionId"] == "cli-b"
    with db._lock:
        row = db._conn.execute(
            "SELECT group_name, reason FROM desktop_registry_conflicts"
        ).fetchone()
    assert row["group_name"] == "protected:cliSessionId"
    assert row["reason"] == "protected_linkage_divergence"


def test_run_min_interval_throttles(tmp_path, store) -> None:
    a, b, c = _roots(tmp_path)
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100)
    clock = [0.0]
    worker = DesktopRegistrySyncWorker(
        store,
        registry_roots=(a, b, c),
        run_min_interval_seconds=300.0,
        monotonic=lambda: clock[0],
    )

    first = worker.run_once()
    assert first.get("throttled", 0) == 0
    clock[0] = 100.0
    assert worker.run_once()["throttled"] == 1
    clock[0] = 400.0
    assert worker.run_once()["throttled"] == 0


def test_worker_requires_registry_roots(store) -> None:
    with pytest.raises(ValueError):
        DesktopRegistrySyncWorker(store, registry_roots=(), run_min_interval_seconds=0)


def test_unknown_key_record_is_replicated_and_verified(tmp_path, store) -> None:
    # End-to-end pin of the 2026-09-06 live signature: a brand-new record carrying a
    # key the planner cannot classify must still be replicated to the other roots,
    # verify clean, advance its decided baselines, and leave the unknown group as a
    # standing conflict rather than a growing verify_failed_files count.
    a, b, c = _roots(tmp_path)
    _write_record(a, "local_one", mtime_ns=100, futureDesktopField="x")
    b.mkdir()
    c.mkdir()

    worker = _worker(store, (a, b, c))
    counters = worker.run_once()

    assert counters["created"] == 2
    assert counters["raced"] == 0
    assert counters["verify_failures"] == 0
    assert counters["conflicts"] == 1
    assert counters["baseline_rows_advanced"] > 0
    for root in (b, c):
        assert _read(root, "local_one")["futureDesktopField"] == "x"
        assert _read(root, "local_one")["title"] == "Original"
    assert store.pending_desktop_registry_run() is None

    second = worker.run_once()
    assert second["created"] == 0
    assert second["patched"] == 0
    assert second["verify_failures"] == 0
    assert second["conflicts"] == 1


# --------------------------------------------------------- liveness heartbeat
#
# 2026-09-07: the drift monitor could not tell a STOPPED worker from a
# CONVERGED one, because both signals it had -- ``desktop_registry_runs``
# (staged only ``if mutations``) and ``desktop_registry_conflicts.last_seen_at``
# (moves only while conflicts stand) -- go stale on a healthy idle worker.
# Measured over a week of healthy operation the newest-run age passed an hour
# 18 times and reached 26.1h overnight.  The heartbeat is the unambiguous
# signal; these pin the property that makes it one.


def _heartbeat(store):
    return store.get_state(WORKER_HEARTBEAT_STATE_KEY)


def test_converged_cycle_still_beats_though_it_stages_no_run(
    tmp_path, store
) -> None:
    """THE load-bearing property: a cycle with nothing to do must still beat.

    Asserts the absence of a run row in the same breath, because that absence
    is exactly what used to read as "the worker stopped".
    """
    a, b, c = _roots(tmp_path)
    for root in (a, b, c):
        _write_record(root, "local_same", mtime_ns=100, title="Same")
    worker = DesktopRegistrySyncWorker(
        store,
        registry_roots=(a, b, c),
        run_min_interval_seconds=0.0,
        wall_clock=lambda: 5_000.0,
    )
    worker.run_once()  # bootstrap baselines
    store.set_state(WORKER_HEARTBEAT_STATE_KEY, {"at": 0.0})

    counters = worker.run_once()

    assert counters["patched"] == 0 and counters["created"] == 0
    assert store.pending_desktop_registry_run() is None
    beat = _heartbeat(store)
    assert beat is not None and beat["at"] == 5_000.0


def test_throttled_call_does_not_beat(tmp_path, store) -> None:
    """A throttled call did no work; letting it beat would forge liveness."""
    a, b, c = _roots(tmp_path)
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, title="One")
    clock = iter([1_000.0, 2_000.0])
    worker = DesktopRegistrySyncWorker(
        store,
        registry_roots=(a, b, c),
        run_min_interval_seconds=10_000.0,
        wall_clock=lambda: next(clock),
    )
    counters = worker.run_once()
    assert counters["throttled"] == 0
    first = _heartbeat(store)
    assert first is not None and first["at"] == 1_000.0

    counters = worker.run_once()

    assert counters["throttled"] == 1
    assert _heartbeat(store)["at"] == 1_000.0  # unmoved


def test_scan_failure_does_not_beat(tmp_path, store, monkeypatch) -> None:
    """A leg that is alive but converging nothing must go stale, not read OK."""
    a, b, c = _roots(tmp_path)
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, title="One")
    worker = DesktopRegistrySyncWorker(
        store,
        registry_roots=(a, b, c),
        run_min_interval_seconds=0.0,
        wall_clock=lambda: 7_000.0,
    )
    monkeypatch.setattr(
        "session_bridge.desktop_registry_worker.scan_desktop_registry_roots",
        _raise_scan_error,
    )

    counters = worker.run_once()

    assert counters["scan_failed"] == 1
    assert _heartbeat(store) is None


def _raise_scan_error(*args, **kwargs):
    raise RegistryScanError("unstable")


def test_beat_advances_across_cycles(tmp_path, store) -> None:
    a, b, c = _roots(tmp_path)
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, title="One")
    clock = iter([100.0, 200.0, 300.0])
    worker = DesktopRegistrySyncWorker(
        store,
        registry_roots=(a, b, c),
        run_min_interval_seconds=0.0,
        wall_clock=lambda: next(clock),
    )
    seen = []
    for _ in range(3):
        worker.run_once()
        seen.append(_heartbeat(store)["at"])
    assert seen == [100.0, 200.0, 300.0]


def test_a_failing_beat_never_costs_a_reconciliation(tmp_path, store) -> None:
    """Telemetry is not allowed to break the work it is reporting on."""
    a, b, c = _roots(tmp_path)
    _write_record(a, "local_one", mtime_ns=100, title="Wanted")
    _write_record(b, "local_one", mtime_ns=100, title="Wanted")
    _write_record(c, "local_one", mtime_ns=50, title="Stale")
    worker = DesktopRegistrySyncWorker(
        store,
        registry_roots=(a, b, c),
        run_min_interval_seconds=0.0,
    )

    def _explode(*args, **kwargs):
        raise RuntimeError("state write failed")

    worker._store = _StoreWithBrokenSetState(store, _explode)

    counters = worker.run_once()

    assert counters["examined"] >= 1
    assert counters["scan_failed"] == 0
    # The convergence itself still happened and committed.
    assert _read(c, "local_one")["title"] == "Wanted"


class _StoreWithBrokenSetState:
    """Delegates everything except ``set_state``, which raises."""

    def __init__(self, inner, explode):
        self._inner = inner
        self._explode = explode

    def set_state(self, *args, **kwargs):
        self._explode()

    def __getattr__(self, name):
        return getattr(self._inner, name)
