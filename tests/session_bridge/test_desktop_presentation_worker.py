from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_state import SessionDB
from session_bridge.desktop_presentation_worker import (
    PRESENTATION_HEARTBEAT_STATE_KEY,
    DesktopPresentationSyncWorker,
)
from session_bridge.store import SessionBridgeStore


@pytest.fixture
def store(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    try:
        yield SessionBridgeStore(db, clock=lambda: 100.0)
    finally:
        db.close()


def _config(starred: list[str]) -> dict:
    return {
        "preferences": {
            "epitaxyPrefs": {
                "starred-local-code-sessions": starred,
                "dframe-local-slice": {
                    "pinnedOrder": [f"code:{session_id}" for session_id in reversed(starred)]
                },
            }
        }
    }


def _root(path: Path, starred: list[str], known: list[str]) -> tuple[Path, Path]:
    path.mkdir()
    config = path / "claude_desktop_config.json"
    config.write_text(json.dumps(_config(starred)), encoding="utf-8")
    sessions = path / "sessions"
    sessions.mkdir()
    for session_id in known:
        (sessions / f"{session_id}.json").write_text(
            json.dumps({"sessionId": session_id}), encoding="utf-8"
        )
    return config, sessions


def _worker(store, roots, active):
    return DesktopPresentationSyncWorker(
        store,
        roots=roots,
        active_root=lambda: active[0],
        run_min_interval_seconds=0,
        wall_clock=lambda: 500.0,
    )


def test_bootstrap_patches_dormant_root_but_withholds_baseline_until_live_repair(
    tmp_path: Path, store
) -> None:
    a = _root(tmp_path / "a", ["local_a"], ["local_a"])
    b = _root(tmp_path / "b", [], ["local_a"])
    active = ["b"]
    worker = _worker(store, {"a": a, "b": b}, active)

    counters = worker.run_once()

    assert counters["pending_active"] == 1
    assert counters["patched"] == 0
    assert store.load_desktop_surface_baselines("presentation") == []
    assert store.get_state(PRESENTATION_HEARTBEAT_STATE_KEY)["pending_active"] == 1


def test_supported_live_repair_allows_next_cycle_to_accept_baseline(
    tmp_path: Path, store
) -> None:
    a = _root(tmp_path / "a", ["local_a"], ["local_a"])
    b = _root(tmp_path / "b", [], ["local_a"])
    active = ["b"]
    worker = _worker(store, {"a": a, "b": b}, active)
    worker.run_once()

    b[0].write_text(json.dumps(_config(["local_a"])), encoding="utf-8")
    counters = worker.run_once()

    assert counters["pending_active"] == 0
    assert counters["baseline_rows_advanced"] == 2
    assert len(store.load_desktop_surface_baselines("presentation")) == 2


def test_later_live_change_is_prepositioned_into_dormant_root(
    tmp_path: Path, store
) -> None:
    a = _root(tmp_path / "a", ["local_a"], ["local_a", "local_b"])
    b = _root(tmp_path / "b", ["local_a"], ["local_a", "local_b"])
    active = ["a"]
    worker = _worker(store, {"a": a, "b": b}, active)
    worker.run_once()

    a[0].write_text(json.dumps(_config(["local_a", "local_b"])), encoding="utf-8")
    counters = worker.run_once()

    assert counters["patched"] == 1
    assert json.loads(b[0].read_text(encoding="utf-8"))["preferences"]["epitaxyPrefs"][
        "starred-local-code-sessions"
    ] == ["local_a", "local_b"]


def test_concurrent_change_records_conflict_and_writes_no_config(tmp_path: Path, store) -> None:
    ids = ["local_a", "local_b", "local_c"]
    a = _root(tmp_path / "a", ["local_a"], ids)
    b = _root(tmp_path / "b", ["local_a"], ids)
    active = [None]
    worker = _worker(store, {"a": a, "b": b}, active)
    worker.run_once()
    a[0].write_text(json.dumps(_config(["local_a", "local_b"])), encoding="utf-8")
    b[0].write_text(json.dumps(_config(["local_a", "local_c"])), encoding="utf-8")

    counters = worker.run_once()

    assert counters["conflicts"] == 1
    assert counters["patched"] == 0


def test_worker_rejects_active_root_outside_enrollment(tmp_path: Path, store) -> None:
    a = _root(tmp_path / "a", [], [])
    worker = _worker(store, {"a": a}, ["missing"])

    counters = worker.run_once()

    assert counters["scan_failed"] == 1
    assert store.get_state(PRESENTATION_HEARTBEAT_STATE_KEY) is None
