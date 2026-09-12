from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_state import SessionDB
from session_bridge.desktop_scheduled_catalog import CatalogConflict
from session_bridge.desktop_scheduled_handoff import (
    CONFIRMATION,
    OWNER_STATE_KEY,
    DesktopScheduledHandoff,
)
from session_bridge.store import SessionBridgeStore


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
        "lastRunAt": "2026-09-11T14:00:00Z" if enabled else None,
        "lastScheduledFor": None,
        "missedRunScanFloor": None,
        "notifySessionId": None,
    }


def _catalog(path: Path, tasks: list[dict]) -> Path:
    path.mkdir()
    target = path / "scheduled-tasks.json"
    target.write_text(json.dumps({"scheduledTasks": tasks}), encoding="utf-8")
    return target


@pytest.fixture
def fixture(tmp_path: Path):
    db = SessionDB(tmp_path / "state.db")
    store = SessionBridgeStore(db, clock=lambda: 100.0)
    prompts = tmp_path / "prompts"
    (prompts / "watch").mkdir(parents=True)
    (prompts / "watch" / "SKILL.md").write_text("prompt", encoding="utf-8")
    source = _catalog(tmp_path / "source", [_task("watch", True)])
    target = _catalog(tmp_path / "target", [])
    handoff = DesktopScheduledHandoff(
        store,
        catalogs={"source": source, "target": target},
        prompt_root=prompts,
        backup_root=tmp_path / "outside-backups",
        live_target="target",
        clock=lambda: 500.0,
    )
    try:
        yield handoff, store, source, target, tmp_path
    finally:
        db.close()


def test_plan_is_read_only_and_names_disable_phase(fixture) -> None:
    handoff, _, source, target, _ = fixture
    before = {source: source.read_bytes(), target: target.read_bytes()}

    plan = handoff.plan(
        source_root_id="source", target_root_id="target", task_ids=("watch",)
    )

    assert plan["phase"] == "disable_old_owners"
    assert plan["task_ids"] == ["watch"]
    assert {path: path.read_bytes() for path in before} == before


def test_partial_enabled_source_set_is_refused(fixture) -> None:
    handoff, _, source, _, _ = fixture
    rows = json.loads(source.read_text(encoding="utf-8"))
    rows["scheduledTasks"].append(_task("other", True))
    source.write_text(json.dumps(rows), encoding="utf-8")
    other_prompt = handoff._prompt_root / "other"
    other_prompt.mkdir()
    (other_prompt / "SKILL.md").write_text("prompt", encoding="utf-8")

    with pytest.raises(CatalogConflict, match="complete enabled source set"):
        handoff.plan(
            source_root_id="source", target_root_id="target", task_ids=("watch",)
        )


def test_apply_requires_exact_confirmation(fixture) -> None:
    handoff, _, _, _, _ = fixture
    with pytest.raises(CatalogConflict, match="confirmation"):
        handoff.apply(
            source_root_id="source",
            target_root_id="target",
            task_ids=("watch",),
            confirmation="no",
        )


def test_two_phase_apply_disables_then_enables_and_records_owner(fixture) -> None:
    handoff, store, source, target, tmp_path = fixture

    first = handoff.apply(
        source_root_id="source",
        target_root_id="target",
        task_ids=("watch",),
        confirmation=CONFIRMATION,
    )
    assert first["phase"] == "disable_old_owners"
    assert json.loads(source.read_text(encoding="utf-8"))["scheduledTasks"][0]["enabled"] is False
    assert store.get_state(OWNER_STATE_KEY) is None
    backup = Path(first["backup"])
    assert backup.is_relative_to(tmp_path / "outside-backups")
    assert (backup / "manifest.json").is_file()

    assert store.get_state("session-bridge:desktop-scheduled-catalog:pending-handoff")[
        "target_root_id"
    ] == "target"
    handoff._live_target = None
    handoff._live_status = "none"
    second = handoff.apply(
        source_root_id="source",
        target_root_id="target",
        task_ids=("watch",),
        confirmation=CONFIRMATION,
    )
    assert second["phase"] == "enable_target"
    enabled = json.loads(target.read_text(encoding="utf-8"))["scheduledTasks"][0]
    assert enabled["enabled"] is True
    assert enabled["cwd"] == "C:/work"
    assert enabled["lastRunAt"] == "2026-09-11T14:00:00Z"
    assert store.get_state(OWNER_STATE_KEY)["root_id"] == "target"


def test_ambiguous_process_state_refuses_target_enable(fixture) -> None:
    handoff, store, source, _, _ = fixture
    rows = json.loads(source.read_text(encoding="utf-8"))
    rows["scheduledTasks"][0]["enabled"] = False
    source.write_text(json.dumps(rows), encoding="utf-8")
    store.set_state(
        "session-bridge:desktop-scheduled-catalog:pending-handoff",
        {"source_root_id": "source", "target_root_id": "target", "task_ids": ["watch"]},
    )
    handoff._live_target = None
    handoff._live_status = "ambiguous"

    with pytest.raises(CatalogConflict, match="provably closed"):
        handoff.plan(
            source_root_id="source", target_root_id="target", task_ids=("watch",)
        )


def test_live_target_mismatch_refuses_before_backup_or_write(fixture) -> None:
    handoff, _, source, _, tmp_path = fixture
    before = source.read_bytes()
    handoff._live_target = "source"

    with pytest.raises(CatalogConflict, match="one live"):
        handoff.apply(
            source_root_id="source",
            target_root_id="target",
            task_ids=("watch",),
            confirmation=CONFIRMATION,
        )

    assert source.read_bytes() == before
    assert not (tmp_path / "outside-backups").exists()

@pytest.mark.parametrize("corrupt_authority", [False, True])
def test_committed_owner_recovery_preserves_new_task_and_requires_exact_receipt(fixture, corrupt_authority):
    handoff, store, source, target, tmp_path = fixture
    handoff.apply(source_root_id="source", target_root_id="target", task_ids=["watch"], confirmation=CONFIRMATION)
    handoff._live_target = None
    handoff._live_status = "none"
    receipt = handoff.apply(source_root_id="source", target_root_id="target", task_ids=["watch"], confirmation=CONFIRMATION)
    new_task = _task("new-quota-check", True)
    target.write_text(json.dumps({"scheduledTasks": [new_task]}), encoding="utf-8")
    before = target.read_bytes()
    kwargs = dict(source_root_id="source", target_root_id="target", task_ids=["watch"],
                  recover_committed_run=receipt["run_id"] if not corrupt_authority else "unknown")
    if corrupt_authority:
        with pytest.raises(CatalogConflict, match="committed"):
            handoff.apply(**kwargs, confirmation=CONFIRMATION)
        assert target.read_bytes() == before
        return
    plan = handoff.plan(**kwargs)
    assert target.read_bytes() == before
    assert plan["phase"] == "enable_target"
    result = handoff.apply(**kwargs, confirmation=CONFIRMATION)
    tasks = {row["id"]: row for row in json.loads(target.read_text(encoding="utf-8"))["scheduledTasks"]}
    assert tasks["new-quota-check"] == new_task
    assert tasks["watch"]["enabled"] is True
    assert tasks["watch"]["createdAt"] == 1788972033605
    assert not any(row["enabled"] for row in json.loads(source.read_text(encoding="utf-8"))["scheduledTasks"])
    backups = list(Path(result["backup"]).glob("*.scheduled-tasks.json"))
    assert len(backups) == 1 and backups[0].read_bytes() == before


@pytest.mark.parametrize("conflict", ["desktop_open", "owner_changed", "selection_changed", "target_present", "old_owner_enabled"])
def test_committed_recovery_refuses_changed_authority_without_writes(fixture, conflict):
    handoff, store, source, target, tmp_path = fixture
    handoff.apply(source_root_id="source", target_root_id="target", task_ids=["watch"], confirmation=CONFIRMATION)
    handoff._live_target = None
    handoff._live_status = "none"
    receipt = handoff.apply(source_root_id="source", target_root_id="target", task_ids=["watch"], confirmation=CONFIRMATION)
    target.write_text(json.dumps({"scheduledTasks": []}), encoding="utf-8")
    selected = ["watch"]
    if conflict == "desktop_open":
        handoff._live_status = "one"
    elif conflict == "owner_changed":
        store.set_state(OWNER_STATE_KEY, {"root_id": "elsewhere", "source_root_id": "source"})
    elif conflict == "selection_changed":
        (handoff._prompt_root / "other").mkdir()
        (handoff._prompt_root / "other" / "SKILL.md").write_text("prompt")
        source.write_text(json.dumps({"scheduledTasks": [_task("watch", False), _task("other", False)]}))
        selected.append("other")
    elif conflict == "target_present":
        target.write_text(json.dumps({"scheduledTasks": [_task("watch", False)]}))
    elif conflict == "old_owner_enabled":
        source.write_text(json.dumps({"scheduledTasks": [_task("watch", True)]}))
    before = {path: path.read_bytes() for path in (source, target)}
    backup_dirs = set((tmp_path / "outside-backups").iterdir())
    with pytest.raises(CatalogConflict):
        handoff.apply(source_root_id="source", target_root_id="target", task_ids=selected,
                      recover_committed_run=receipt["run_id"], confirmation=CONFIRMATION)
    assert {path: path.read_bytes() for path in before} == before
    assert set((tmp_path / "outside-backups").iterdir()) == backup_dirs
