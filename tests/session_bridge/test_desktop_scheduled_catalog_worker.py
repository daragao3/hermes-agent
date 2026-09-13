from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_state import SessionDB
from session_bridge.desktop_scheduled_catalog_worker import (
    LANE,
    SCHEDULED_CATALOG_HEARTBEAT_STATE_KEY,
    DesktopScheduledCatalogSyncWorker,
)
from session_bridge.store import SessionBridgeStore


@pytest.fixture
def store(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    try:
        yield SessionBridgeStore(db, clock=lambda: 100.0)
    finally:
        db.close()


def _task(task_id: str, enabled: bool) -> dict:
    return {
        "id": task_id,
        "createdAt": 1788972033605,
        "displayName": task_id,
        "cronExpression": "7 * * * *",
        "fireAt": None,
        "cwd": "C:/work",
        "model": "claude-opus-5",
        "permissionMode": "bypassPermissions",
        "approvedPermissions": [],
        "useWorktree": False,
        "filePath": f"C:/prompts/{task_id}/SKILL.md",
        "enabled": enabled,
        "lastRunAt": None,
        "lastScheduledFor": None,
        "missedRunScanFloor": None,
        "notifySessionId": None,
    }


def _conflict_rows(store) -> list[tuple[str, str]]:
    db = store.db
    with db._lock:
        rows = db._conn.execute(
            "SELECT item_id, reason FROM desktop_surface_conflicts WHERE lane = ? "
            "ORDER BY item_id",
            (LANE,),
        ).fetchall()
    return [(row["item_id"], row["reason"]) for row in rows]


def _store(path: Path, tasks: list[dict]) -> Path:
    path.mkdir()
    target = path / "scheduled-tasks.json"
    target.write_text(json.dumps({"scheduledTasks": tasks}), encoding="utf-8")
    return target


def test_worker_replication_patches_dormant_catalog_only(tmp_path: Path, store) -> None:
    prompts = tmp_path / "prompts"
    (prompts / "watch").mkdir(parents=True)
    (prompts / "watch" / "SKILL.md").write_text("prompt", encoding="utf-8")
    source = _store(tmp_path / "source", [_task("watch", True)])
    dormant = _store(tmp_path / "dormant", [])
    active = _store(tmp_path / "active", [])
    worker = DesktopScheduledCatalogSyncWorker(
        store,
        catalogs={"source": source, "dormant": dormant, "active": active},
        source_root=lambda: "source",
        active_root=lambda: "active",
        prompt_root=prompts,
        run_min_interval_seconds=0,
        wall_clock=lambda: 500.0,
    )

    counters = worker.run_once()

    assert counters["patched"] == 1
    assert counters["pending_active"] == 1
    assert json.loads(dormant.read_text(encoding="utf-8"))["scheduledTasks"][0]["enabled"] is False
    assert json.loads(active.read_text(encoding="utf-8"))["scheduledTasks"] == []
    assert store.get_state(SCHEDULED_CATALOG_HEARTBEAT_STATE_KEY)["pending_active"] == 1


def test_worker_records_conflict_for_task_without_native_creation_timestamp(
    tmp_path: Path, store
) -> None:
    prompts = tmp_path / "prompts"
    (prompts / "watch").mkdir(parents=True)
    (prompts / "watch" / "SKILL.md").write_text("prompt", encoding="utf-8")
    stale = _task("watch", True)
    del stale["createdAt"]
    source = _store(tmp_path / "source", [stale])
    dormant = _store(tmp_path / "dormant", [])
    worker = DesktopScheduledCatalogSyncWorker(
        store,
        catalogs={"source": source, "dormant": dormant},
        source_root=lambda: "source",
        active_root=lambda: None,
        prompt_root=prompts,
        run_min_interval_seconds=0,
    )

    counters = worker.run_once()

    # The run completes and NAMES the offending task rather than failing the
    # whole scan closed with no pointer to it.
    assert counters["scan_failed"] == 0
    assert counters["conflicts"] == 1
    assert counters["patched"] == 0
    assert json.loads(dormant.read_text(encoding="utf-8"))["scheduledTasks"] == []
    assert store.get_state(SCHEDULED_CATALOG_HEARTBEAT_STATE_KEY)["conflicts"] == 1
    assert _conflict_rows(store) == [("watch", "created_at_missing")]


def test_worker_replicates_healthy_tasks_alongside_an_unportable_one(
    tmp_path: Path, store
) -> None:
    prompts = tmp_path / "prompts"
    for task_id in ("watch", "stale", "orphan"):
        (prompts / task_id).mkdir(parents=True)
        (prompts / task_id / "SKILL.md").write_text("prompt", encoding="utf-8")
    stale = _task("stale", True)
    del stale["createdAt"]
    orphan = _task("orphan", True)
    orphan["createdAt"] = "not-a-timestamp"
    source = _store(tmp_path / "source", [_task("watch", True), stale, orphan])
    dormant = _store(tmp_path / "dormant", [])
    worker = DesktopScheduledCatalogSyncWorker(
        store,
        catalogs={"source": source, "dormant": dormant},
        source_root=lambda: "source",
        active_root=lambda: None,
        prompt_root=prompts,
        run_min_interval_seconds=0,
    )

    counters = worker.run_once()

    # One unportable task must not block replication of every other task.
    assert counters["scan_failed"] == 0
    assert counters["patched"] == 1
    assert counters["conflicts"] == 2
    replicated = json.loads(dormant.read_text(encoding="utf-8"))["scheduledTasks"]
    assert [row["id"] for row in replicated] == ["watch"]
    assert replicated[0]["enabled"] is False
    assert _conflict_rows(store) == [
        ("orphan", "created_at_missing"),
        ("stale", "created_at_missing"),
    ]


def test_worker_missing_prompt_records_conflict_without_mutation(tmp_path: Path, store) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    source = _store(tmp_path / "source", [_task("missing", True)])
    target = _store(tmp_path / "target", [])
    worker = DesktopScheduledCatalogSyncWorker(
        store,
        catalogs={"source": source, "target": target},
        source_root=lambda: "source",
        active_root=lambda: "source",
        prompt_root=prompts,
        run_min_interval_seconds=0,
    )

    counters = worker.run_once()

    assert counters["conflicts"] == 1
    assert counters["patched"] == 0


def test_worker_fails_closed_when_source_is_not_enrolled(tmp_path: Path, store) -> None:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    target = _store(tmp_path / "target", [])
    worker = DesktopScheduledCatalogSyncWorker(
        store,
        catalogs={"target": target},
        source_root=lambda: "missing",
        active_root=lambda: "target",
        prompt_root=prompts,
        run_min_interval_seconds=0,
    )

    assert worker.run_once()["scan_failed"] == 1
    assert store.get_state(SCHEDULED_CATALOG_HEARTBEAT_STATE_KEY) is None
