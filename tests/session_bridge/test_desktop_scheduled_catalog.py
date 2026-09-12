from __future__ import annotations

import json
from pathlib import Path

import pytest

from session_bridge.desktop_scheduled_catalog import (
    CatalogMutationConflict,
    apply_catalog_mutation,
    build_replication_plan,
    build_handoff_plan,
    scan_catalogs,
)


def _task(task_id: str, *, enabled: bool, cwd: str = "C:/work", **fields) -> dict:
    return {
        "id": task_id,
        "createdAt": 1788972033605,
        "displayName": task_id,
        "cronExpression": "7 * * * *",
        "fireAt": None,
        "cwd": cwd,
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
        **fields,
    }


def _write_store(root: Path, tasks: list[dict]) -> Path:
    root.mkdir(parents=True)
    path = root / "scheduled-tasks.json"
    path.write_text(
        json.dumps(
            {
                "scheduledTasks": tasks,
                "recordedSkips": {"keep": True},
                "sundayAliasBoundaryStamped": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _prompts(root: Path, *task_ids: str) -> Path:
    for task_id in task_ids:
        path = root / task_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(f"---\nname: {task_id}\n---\n", encoding="utf-8")
    return root


def _scan(prompt_root: Path, **stores: Path):
    return scan_catalogs(stores, prompt_root=prompt_root)


def test_disabled_replication_copies_definition_without_execution_state(tmp_path: Path) -> None:
    prompts = _prompts(tmp_path / "prompts", "watch")
    source = _write_store(
        tmp_path / "source",
        [_task("watch", enabled=True, lastRunAt="2026-09-11T14:00:00Z")],
    )
    target = _write_store(tmp_path / "target", [])
    scan = _scan(prompts, source=source, target=target)

    plan = build_replication_plan(scan, source_root_id="source", active_root_id="source")

    assert len(plan.mutations) == 1
    mutation = plan.mutations[0]
    assert mutation.root_id == "target"
    copied = json.loads(mutation.after_bytes)["scheduledTasks"][0]
    assert copied["enabled"] is False
    assert copied.get("lastRunAt") is None
    assert copied.get("lastScheduledFor") is None
    assert copied["cwd"] == "C:/work"
    assert copied["cronExpression"] == "7 * * * *"


def test_replication_preserves_target_execution_state_and_unrelated_store_keys(tmp_path: Path) -> None:
    prompts = _prompts(tmp_path / "prompts", "watch")
    source = _write_store(tmp_path / "source", [_task("watch", enabled=True, cwd="C:/correct")])
    target = _write_store(
        tmp_path / "target",
        [_task("watch", enabled=False, cwd="C:/stale", lastRunAt="2026-09-10T10:00:00Z")],
    )

    plan = build_replication_plan(
        _scan(prompts, source=source, target=target),
        source_root_id="source",
        active_root_id="source",
    )
    copied = json.loads(plan.mutations[0].after_bytes)
    task = copied["scheduledTasks"][0]
    assert task["cwd"] == "C:/correct"
    assert task["enabled"] is False
    assert task["lastRunAt"] == "2026-09-10T10:00:00Z"
    assert copied["recordedSkips"] == {"keep": True}


def test_missing_prompt_is_quarantined_not_replicated(tmp_path: Path) -> None:
    prompts = _prompts(tmp_path / "prompts")
    source = _write_store(tmp_path / "source", [_task("missing", enabled=True)])
    target = _write_store(tmp_path / "target", [])

    plan = build_replication_plan(
        _scan(prompts, source=source, target=target),
        source_root_id="source",
        active_root_id="source",
    )

    assert plan.mutations == ()
    assert plan.conflicts == (("missing", "prompt_missing"),)


def test_replication_never_patches_active_target(tmp_path: Path) -> None:
    prompts = _prompts(tmp_path / "prompts", "watch")
    source = _write_store(tmp_path / "source", [_task("watch", enabled=True)])
    target = _write_store(tmp_path / "target", [])

    plan = build_replication_plan(
        _scan(prompts, source=source, target=target),
        source_root_id="source",
        active_root_id="target",
    )

    assert plan.mutations == ()
    assert plan.pending_active_roots == ("target",)


def test_handoff_first_cycle_disables_every_non_target_owner(tmp_path: Path) -> None:
    prompts = _prompts(tmp_path / "prompts", "watch", "stale-only")
    source = _write_store(
        tmp_path / "source",
        [_task("watch", enabled=True, lastRunAt="2026-09-11T14:00:00Z")],
    )
    stale = _write_store(
        tmp_path / "stale",
        [_task("watch", enabled=True), _task("stale-only", enabled=True)],
    )
    target = _write_store(tmp_path / "target", [])

    plan = build_handoff_plan(
        _scan(prompts, source=source, stale=stale, target=target),
        source_root_id="source",
        target_root_id="target",
        task_ids=("watch",),
    )

    assert plan.phase == "disable_old_owners"
    assert {mutation.root_id for mutation in plan.mutations} == {"source", "stale"}
    stale_after = next(
        json.loads(mutation.after_bytes)
        for mutation in plan.mutations
        if mutation.root_id == "stale"
    )
    assert all(task["enabled"] is False for task in stale_after["scheduledTasks"])


def test_handoff_second_cycle_enables_target_only_after_old_owners_are_disabled(tmp_path: Path) -> None:
    prompts = _prompts(tmp_path / "prompts", "watch")
    source = _write_store(
        tmp_path / "source",
        [_task("watch", enabled=False, lastRunAt="2026-09-11T14:00:00Z")],
    )
    stale = _write_store(tmp_path / "stale", [_task("watch", enabled=False)])
    target = _write_store(tmp_path / "target", [])

    plan = build_handoff_plan(
        _scan(prompts, source=source, stale=stale, target=target),
        source_root_id="source",
        target_root_id="target",
        task_ids=("watch",),
    )

    assert plan.phase == "enable_target"
    assert len(plan.mutations) == 1
    assert plan.mutations[0].root_id == "target"
    task = json.loads(plan.mutations[0].after_bytes)["scheduledTasks"][0]
    assert task["enabled"] is True
    assert task["lastRunAt"] == "2026-09-11T14:00:00Z"


def test_named_source_overrides_stale_enabled_definition_during_disable_phase(
    tmp_path: Path,
) -> None:
    prompts = _prompts(tmp_path / "prompts", "watch")
    source = _write_store(tmp_path / "source", [_task("watch", enabled=True, cwd="C:/a")])
    other = _write_store(tmp_path / "other", [_task("watch", enabled=True, cwd="C:/b")])
    target = _write_store(tmp_path / "target", [])

    plan = build_handoff_plan(
        _scan(prompts, source=source, other=other, target=target),
        source_root_id="source",
        target_root_id="target",
        task_ids=("watch",),
    )

    assert plan.phase == "disable_old_owners"
    assert {mutation.root_id for mutation in plan.mutations} == {"source", "other"}


def test_apply_refuses_hash_race(tmp_path: Path) -> None:
    prompts = _prompts(tmp_path / "prompts", "watch")
    source = _write_store(tmp_path / "source", [_task("watch", enabled=True)])
    target = _write_store(tmp_path / "target", [])
    scan = _scan(prompts, source=source, target=target)
    plan = build_replication_plan(scan, source_root_id="source", active_root_id="source")
    raced = json.loads(target.read_text(encoding="utf-8"))
    raced["newKey"] = True
    target.write_text(json.dumps(raced), encoding="utf-8")

    with pytest.raises(CatalogMutationConflict, match="expected hash"):
        apply_catalog_mutation(scan, plan.mutations[0])


def test_second_replication_cycle_is_idempotent(tmp_path: Path) -> None:
    prompts = _prompts(tmp_path / "prompts", "watch")
    source = _write_store(tmp_path / "source", [_task("watch", enabled=True)])
    target = _write_store(tmp_path / "target", [])
    scan = _scan(prompts, source=source, target=target)
    first = build_replication_plan(scan, source_root_id="source", active_root_id="source")
    apply_catalog_mutation(scan, first.mutations[0])

    second = build_replication_plan(
        _scan(prompts, source=source, target=target),
        source_root_id="source",
        active_root_id="source",
    )

    assert second.mutations == ()

@pytest.mark.parametrize("mode", ["handoff", "replication"])
def test_native_manifest_preserves_required_creation_and_omits_optional_nulls(tmp_path, mode):
    source_task = _task("watch", enabled=False, createdAt=1788972033605,
                        userSelectedFolders=["C:/approved"], sourceBranch="topic")
    prompts = _prompts(tmp_path / "prompts", "watch")
    source = _write_store(tmp_path / "source", [source_task])
    target = _write_store(tmp_path / "target", [])
    scan = _scan(prompts, source=source, target=target)
    plan = (build_handoff_plan(scan, source_root_id="source", target_root_id="target", task_ids=["watch"])
            if mode == "handoff" else build_replication_plan(scan, source_root_id="source", active_root_id=None))
    copied = json.loads(plan.mutations[0].after_bytes)["scheduledTasks"][0]
    assert copied["createdAt"] == source_task["createdAt"]
    assert all(value is not None for value in copied.values())
    assert copied["userSelectedFolders"] == source_task["userSelectedFolders"]
    assert copied["sourceBranch"] == "topic"
    assert "notifySessionId" not in copied
