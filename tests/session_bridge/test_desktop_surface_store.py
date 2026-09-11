from __future__ import annotations

import json

import pytest

from hermes_state import SessionDB
from session_bridge.store import SessionBridgeStore


@pytest.fixture
def store(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    try:
        yield SessionBridgeStore(db, clock=lambda: 100.0), db
    finally:
        db.close()


def test_surface_baselines_are_lane_scoped_and_round_trip_values(store) -> None:
    bridge, _ = store
    bridge.upsert_desktop_surface_baselines(
        "presentation",
        [{"root_id": "a", "group_name": "pins", "value_json": '{"x":1}', "revision": 1}],
    )
    bridge.upsert_desktop_surface_baselines(
        "scheduled_catalog",
        [{"root_id": "a", "group_name": "task:t", "value_json": '{"x":2}', "revision": 1}],
    )

    assert bridge.load_desktop_surface_baselines("presentation") == [
        {"root_id": "a", "group_name": "pins", "value_json": '{"x":1}', "revision": 1}
    ]
    assert bridge.load_desktop_surface_baselines("scheduled_catalog")[0]["value_json"] == '{"x":2}'


def test_pending_surface_runs_are_independent_per_lane(store) -> None:
    bridge, _ = store
    bridge.stage_desktop_surface_run("presentation", "p1", 1, "{}")
    bridge.stage_desktop_surface_run("scheduled_catalog", "s1", 1, "{}")

    assert bridge.pending_desktop_surface_run("presentation")["id"] == "p1"
    assert bridge.pending_desktop_surface_run("scheduled_catalog")["id"] == "s1"
    with pytest.raises(ValueError, match="still pending"):
        bridge.stage_desktop_surface_run("presentation", "p2", 1, "{}")

    bridge.finish_desktop_surface_run("presentation", "p1", "committed", resolution=None)
    assert bridge.pending_desktop_surface_run("presentation") is None
    assert bridge.pending_desktop_surface_run("scheduled_catalog")["id"] == "s1"


def test_surface_conflict_replacement_preserves_first_seen(store) -> None:
    bridge, db = store
    conflict = {
        "item_id": "config",
        "group_name": "pins",
        "reason": "concurrent_divergence",
        "candidates_json": json.dumps({"a": "x", "b": "y"}),
    }
    bridge.replace_desktop_surface_conflicts("presentation", [conflict])
    bridge._clock = lambda: 200.0
    bridge.replace_desktop_surface_conflicts("presentation", [conflict])

    with db._lock:
        row = db._conn.execute(
            "SELECT first_seen_at, last_seen_at FROM desktop_surface_conflicts "
            "WHERE lane = 'presentation'"
        ).fetchone()
    assert (row["first_seen_at"], row["last_seen_at"]) == (100.0, 200.0)


def test_surface_store_rejects_invalid_lane(store) -> None:
    bridge, _ = store
    with pytest.raises(ValueError, match="lane"):
        bridge.load_desktop_surface_baselines("bad lane")
