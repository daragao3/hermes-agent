from __future__ import annotations

import itertools
import json
import os
from pathlib import Path

import pytest

from session_bridge.desktop_registry import (
    DESKTOP_REGISTRY_GROUPING_VERSION,
    RegistryBaseline,
    RegistryMutationConflict,
    RegistryScanError,
    apply_registry_mutation,
    build_registry_sync_plan,
    canonical_group_value,
    scan_desktop_registry_roots,
    verify_registry_sync_plan,
)


_ABSENT = object()


def _write_record(
    root: Path,
    session_id: str,
    *,
    mtime_ns: int,
    **fields: object,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{session_id}.json"
    record = {
        "sessionId": session_id,
        "title": "Original",
        "isArchived": False,
        "lastActivityAt": 1000,
        **fields,
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def _scan(*roots: Path):
    return scan_desktop_registry_roots(roots)


def _root_id(scan, root: Path) -> str:
    expected = str(root.resolve()).casefold()
    return next(
        root_id
        for root_id, observation in scan.roots.items()
        if observation.canonical_path.casefold() == expected
    )


def test_grouping_registry_has_an_explicit_version_and_every_live_field() -> None:
    assert DESKTOP_REGISTRY_GROUPING_VERSION == 1
    record = {
        "sessionId": "local_one",
        "title": "Title",
        "isArchived": False,
        "lastActivityAt": 1,
        "lastFocusedAt": 1,
        "completedTurns": 3,
        "worktreeName": "tree",
        "worktreePath": "C:/tree",
        "sourceBranch": "main",
        "writtenBranches": ["topic"],
        "error": "failed",
        "errorAt": 2,
        "errorCategory": "runtime",
        "priorErrorMark": {"x": 1},
        "prNumber": 1,
        "prRepository": "owner/repo",
        "prState": "open",
        "prUrl": "https://example.test/pr/1",
        "permissionMode": "default",
        "chromePermissionMode": "default",
        "alwaysAllowedReasons": [],
        "sessionPermissionUpdates": [],
        "sessionSettings": {},
        "remoteMcpServersConfig": {},
        "enabledMcpTools": [],
        "backgroundTaskSuggestions": [],
        "resolvedBackgroundTaskSuggestions": [],
        "pendingSystemReminder": None,
    }

    values = canonical_group_value(record)

    assert "identity" not in values
    assert values["worktree"]
    assert values["error-state"]
    assert values["pull-request"]
    assert values["permissions"]
    assert values["mcp"]
    assert values["background-tasks"]
    assert values["field:title"]
    assert values["field:isArchived"]


def test_scan_rejects_filename_session_identity_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "a"
    path = _write_record(root, "local_one", mtime_ns=1)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["sessionId"] = "local_other"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(RegistryScanError, match="identity"):
        _scan(root)


@pytest.mark.parametrize(
    ("raw", "message"),
    (
        ('{"sessionId":"local_one","title":"a","title":"b"}', "duplicate"),
        ('{"sessionId":"local_one","value":NaN}', "constant"),
        ('["local_one"]', "not an object"),
    ),
)
def test_scan_rejects_non_strict_json(
    tmp_path: Path, raw: str, message: str
) -> None:
    root = tmp_path / "a"
    root.mkdir()
    (root / "local_one.json").write_text(raw, encoding="utf-8")

    with pytest.raises(RegistryScanError, match=message):
        _scan(root)


def test_scan_rejects_duplicate_resolved_roots(tmp_path: Path) -> None:
    root = tmp_path / "a"
    root.mkdir()

    with pytest.raises(RegistryScanError, match="duplicate resolved"):
        _scan(root, root)


def test_cli_session_id_collision_does_not_merge_filenames(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("a", "b", "c")]
    for index, root in enumerate(roots):
        _write_record(
            root,
            "local_one",
            mtime_ns=10 + index,
            cliSessionId="shared-cli",
        )
        _write_record(
            root,
            "local_two",
            mtime_ns=20 + index,
            cliSessionId="shared-cli",
        )

    plan = build_registry_sync_plan(_scan(*roots), baselines=())

    assert set(plan.records) == {"local_one.json", "local_two.json"}
    assert not plan.conflicts


def test_bootstrap_chooses_unique_newest_record_per_group_not_whole_record(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(
        a,
        "local_one",
        mtime_ns=100,
        title="Old title",
        isArchived=True,
        destinationOnly="preserve-a",
    )
    _write_record(b, "local_one", mtime_ns=300, title="New title", isArchived=False)
    _write_record(c, "local_one", mtime_ns=200, title="Middle", isArchived=True)

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())
    record = plan.records["local_one.json"]

    assert json.loads(record.desired_groups["field:title"])["value"] == "New title"
    assert json.loads(record.desired_groups["field:isArchived"])["value"] is False
    assert len(record.mutations) == 2
    conflict = next(
        item
        for item in plan.conflicts
        if item.group_name == "unknown:destinationOnly"
    )
    assert conflict.reason == "unknown_field_unclassified"


def test_bootstrap_equal_newest_same_value_is_safe(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Winner")
    _write_record(c, "local_one", mtime_ns=300, title="Winner")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    assert not plan.conflicts
    desired = plan.records["local_one.json"].desired_groups["field:title"]
    assert json.loads(desired)["value"] == "Winner"


def test_bootstrap_equal_newest_different_value_quarantines_without_tiebreak(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="B")
    _write_record(c, "local_one", mtime_ns=300, title="C")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    conflict = next(item for item in plan.conflicts if item.group_name == "field:title")
    assert conflict.reason == "bootstrap_newest_tie"
    assert "field:title" not in plan.records["local_one.json"].desired_groups
    assert all(
        "title" not in mutation.changed_fields
        for mutation in plan.records["local_one.json"].mutations
    )


def test_bootstrap_treats_absent_as_distinct_from_null(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, promptSuggestion="old")
    _write_record(b, "local_one", mtime_ns=300)
    _write_record(c, "local_one", mtime_ns=200, promptSuggestion=None)

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())
    desired = json.loads(
        plan.records["local_one.json"].desired_groups["field:promptSuggestion"]
    )

    assert desired == {"state": "absent"}
    assert any(
        mutation.changed_fields.get("promptSuggestion") == {"state": "absent"}
        for mutation in plan.records["local_one.json"].mutations
    )


def test_steady_state_propagates_manual_archive_then_unarchive(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, isArchived=False)
    initial_scan = _scan(a, b, c)
    initial_plan = build_registry_sync_plan(initial_scan, baselines=())
    baseline = initial_plan.proposed_baselines

    path = b / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["isArchived"] = True
    path.write_text(json.dumps(record), encoding="utf-8")
    os.utime(path, ns=(200, 200))

    archived_plan = build_registry_sync_plan(_scan(a, b, c), baselines=baseline)
    archived_value = archived_plan.records["local_one.json"].desired_groups[
        "field:isArchived"
    ]
    assert json.loads(archived_value)["value"] is True

    archived_baseline = archived_plan.proposed_baselines
    for root in (a, c):
        other = root / "local_one.json"
        current = json.loads(other.read_text(encoding="utf-8"))
        current["isArchived"] = True
        other.write_text(json.dumps(current), encoding="utf-8")
    unarchived = c / "local_one.json"
    current = json.loads(unarchived.read_text(encoding="utf-8"))
    current["isArchived"] = False
    unarchived.write_text(json.dumps(current), encoding="utf-8")

    unarchived_plan = build_registry_sync_plan(
        _scan(a, b, c), baselines=archived_baseline
    )

    value = unarchived_plan.records["local_one.json"].desired_groups[
        "field:isArchived"
    ]
    assert json.loads(value)["value"] is False
    assert not unarchived_plan.conflicts


def test_steady_state_preserves_unrelated_destination_change(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, title="Base", isStarred=False)
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())

    source = a / "local_one.json"
    source_record = json.loads(source.read_text(encoding="utf-8"))
    source_record["title"] = "Propagated"
    source.write_text(json.dumps(source_record), encoding="utf-8")
    destination = b / "local_one.json"
    destination_record = json.loads(destination.read_text(encoding="utf-8"))
    destination_record["isStarred"] = True
    destination.write_text(json.dumps(destination_record), encoding="utf-8")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=initial.proposed_baselines)
    patch_b = next(
        mutation
        for mutation in plan.records["local_one.json"].mutations
        if mutation.root_id == _root_id(plan.scan, b)
    )

    assert json.loads(patch_b.after_bytes)["title"] == "Propagated"
    assert json.loads(patch_b.after_bytes)["isStarred"] is True


def test_steady_state_equal_concurrent_changes_converge(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, title="Base")
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())

    for root in (a, b):
        path = root / "local_one.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["title"] = "Same update"
        path.write_text(json.dumps(record), encoding="utf-8")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=initial.proposed_baselines)

    assert not plan.conflicts
    desired = plan.records["local_one.json"].desired_groups["field:title"]
    assert json.loads(desired)["value"] == "Same update"
    assert len(plan.records["local_one.json"].mutations) == 1


def test_steady_state_merges_disjoint_replica_changes(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, title="Base", isStarred=False)
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())

    a_record = json.loads((a / "local_one.json").read_text(encoding="utf-8"))
    a_record["title"] = "Changed title"
    (a / "local_one.json").write_text(json.dumps(a_record), encoding="utf-8")
    b_record = json.loads((b / "local_one.json").read_text(encoding="utf-8"))
    b_record["isStarred"] = True
    (b / "local_one.json").write_text(json.dumps(b_record), encoding="utf-8")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=initial.proposed_baselines)
    desired = plan.records["local_one.json"].desired_groups

    assert json.loads(desired["field:title"])["value"] == "Changed title"
    assert json.loads(desired["field:isStarred"])["value"] is True
    assert not plan.conflicts


def test_new_unknown_key_after_baseline_is_quarantined_and_preserved(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100)
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())

    for root, value in ((a, "from-a"), (b, "from-b")):
        path = root / "local_one.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["futureDesktopField"] = value
        path.write_text(json.dumps(record), encoding="utf-8")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=initial.proposed_baselines)

    conflict = next(
        item
        for item in plan.conflicts
        if item.group_name == "unknown:futureDesktopField"
    )
    assert conflict.reason == "unknown_field_unclassified"
    assert "unknown:futureDesktopField" not in plan.records[
        "local_one.json"
    ].desired_groups
    assert not plan.records["local_one.json"].mutations
    assert "futureDesktopField" not in json.loads(
        (c / "local_one.json").read_text(encoding="utf-8")
    )
    assert json.loads((a / "local_one.json").read_text(encoding="utf-8"))[
        "futureDesktopField"
    ] == "from-a"
    assert json.loads((b / "local_one.json").read_text(encoding="utf-8"))[
        "futureDesktopField"
    ] == "from-b"


def test_steady_state_protected_linkage_change_is_quarantined(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, cliSessionId="cli-base")
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())

    path = a / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["cliSessionId"] = "cli-new"
    path.write_text(json.dumps(record), encoding="utf-8")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=initial.proposed_baselines)

    conflict = next(
        item for item in plan.conflicts if item.group_name == "protected:cliSessionId"
    )
    assert conflict.reason == "protected_linkage_divergence"
    assert "protected:cliSessionId" not in plan.records["local_one.json"].desired_groups


def test_steady_state_fills_a_pointer_the_replica_never_learned(
    tmp_path: Path,
) -> None:
    """The exact live failure: replicated while null, then run in one account."""
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, cliSessionId=None)
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())
    assert any(
        baseline.group_name == "protected:cliSessionId"
        for baseline in initial.proposed_baselines
    )

    path = a / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["cliSessionId"] = "cli-learned"
    path.write_text(json.dumps(record), encoding="utf-8")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=initial.proposed_baselines)

    assert not any(
        item.group_name == "protected:cliSessionId" for item in plan.conflicts
    )
    desired = plan.records["local_one.json"].desired_groups["protected:cliSessionId"]
    assert json.loads(desired)["value"] == "cli-learned"
    assert {
        mutation.root_id for mutation in plan.records["local_one.json"].mutations
    } == {_root_id(plan.scan, b), _root_id(plan.scan, c)}


def test_steady_state_never_re_asserts_a_pointer_the_desktop_app_cleared(
    tmp_path: Path,
) -> None:
    """The terminator, and the reason the fill consults the baseline at all.

    Measured 2026-09-07: the desktop app rewrites its own in-memory copy over a
    record it holds open, and two of ten hand-repaired records went back to their
    stale value nine hours later that way -- one of them back to null.  Deciding
    the fill on current values alone would refill it on the next cycle, and the
    app would clear it again, forever.

    An accepted baseline is the memory that stops that: once a real pointer has
    converged for this group, a copy that has gone back to empty is the app
    asserting a value, not a replica lagging behind one.  Quarantine, do not
    refill -- the operator-facing repair path (which can read transcript lengths)
    is where that case belongs.
    """
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, cliSessionId="cli-base")
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())

    path = b / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["cliSessionId"] = None
    path.write_text(json.dumps(record), encoding="utf-8")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=initial.proposed_baselines)

    conflict = next(
        item for item in plan.conflicts if item.group_name == "protected:cliSessionId"
    )
    assert conflict.reason == "protected_linkage_divergence"
    assert (
        "protected:cliSessionId"
        not in plan.records["local_one.json"].desired_groups
    )
    assert all(
        "cliSessionId" not in mutation.changed_fields
        for mutation in plan.records["local_one.json"].mutations
    )


def test_standing_protected_quarantine_is_filled_when_one_pointer_remains(
    tmp_path: Path,
) -> None:
    """A group already in quarantine still reaches the fill on a later cycle.

    Quarantined groups never receive a baseline, so they take the unaccepted-group
    path rather than the steady-state one.  Wiring the fill into only one of the
    two would leave every record that was already standing in quarantine on
    2026-09-07 stuck there.
    """
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, cliSessionId="cli-a")
    _write_record(b, "local_one", mtime_ns=300, cliSessionId="cli-b")
    _write_record(c, "local_one", mtime_ns=200, cliSessionId="cli-a")
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())
    assert not any(
        baseline.group_name == "protected:cliSessionId"
        for baseline in initial.proposed_baselines
    )
    for mutation in initial.records["local_one.json"].mutations:
        root = initial.scan.roots[mutation.root_id].path
        (root / mutation.filename).write_text(mutation.after_bytes, encoding="utf-8")

    path = b / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["cliSessionId"] = None
    path.write_text(json.dumps(record), encoding="utf-8")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=initial.proposed_baselines)

    desired = plan.records["local_one.json"].desired_groups["protected:cliSessionId"]
    assert json.loads(desired)["value"] == "cli-a"
    assert any(
        baseline.group_name == "protected:cliSessionId"
        for baseline in plan.proposed_baselines
    )


def test_fill_can_only_ever_target_a_copy_with_no_pointer(tmp_path: Path) -> None:
    """Exhaustive: the fill NEVER writes into a copy that already holds a pointer.

    This is the property that answers "could a scheduled update path undo the
    desktop app".  It cannot: the fill's precondition is that exactly one distinct
    non-null pointer exists, so every root it patches is one that holds none, and
    a copy holding a real pointer is either the donor or grounds for refusing
    outright.  The app therefore always writes last on any record it has open --
    the worst case is that a patch is silently undone, never that a pointer the
    app wrote is replaced.

    Asserted over all 64 three-root arrangements of {pointer V, pointer W, null,
    absent} rather than a chosen example, because the dangerous case is precisely
    the one nobody thought to write down.
    """
    states: dict[str, object] = {
        "V": "cli-V",
        "W": "cli-W",
        "null": None,
        "absent": _ABSENT,
    }
    patched_at_least_once = 0
    for combination in itertools.product(states, repeat=3):
        roots = []
        for index, (name, state) in enumerate(zip("abc", combination)):
            root = tmp_path / f"{'_'.join(combination)}_{index}_{name}"
            fields = {} if states[state] is _ABSENT else {"cliSessionId": states[state]}
            _write_record(root, "local_one", mtime_ns=100 + index, **fields)
            roots.append(root)
        scan = _scan(*roots)
        plan = build_registry_sync_plan(scan, baselines=())
        mutations = [
            mutation
            for mutation in plan.records["local_one.json"].mutations
            if "cliSessionId" in mutation.changed_fields
        ]
        patched_at_least_once += bool(mutations)
        for mutation in mutations:
            target = Path(scan.roots[mutation.root_id].path) / "local_one.json"
            before = json.loads(target.read_text(encoding="utf-8")).get("cliSessionId")
            assert before is None, (
                f"{combination}: fill would overwrite the live pointer {before!r}"
            )
    # Guard against the assertion above passing vacuously by never firing at all.
    assert patched_at_least_once >= 24


def test_fill_is_refused_when_the_desktop_app_wins_the_race(tmp_path: Path) -> None:
    """The read-then-write race, closed by the existing expected-hash precondition.

    If the app fills the field itself between the scan that planned the fill and
    the write that applies it, the planned patch is stale and would overwrite a
    real pointer with a different one.  It must be refused, not applied.
    """
    a, b = (tmp_path / name for name in ("a", "b"))
    _write_record(a, "local_one", mtime_ns=100, cliSessionId="cli-a")
    _write_record(b, "local_one", mtime_ns=200, cliSessionId=None)
    plan = build_registry_sync_plan(_scan(a, b), baselines=())
    mutation = next(
        item
        for item in plan.records["local_one.json"].mutations
        if "cliSessionId" in item.changed_fields
    )

    path = b / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["cliSessionId"] = "cli-the-app-just-started"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(RegistryMutationConflict):
        apply_registry_mutation(plan.scan, mutation)
    assert (
        json.loads(path.read_text(encoding="utf-8"))["cliSessionId"]
        == "cli-the-app-just-started"
    )


def test_second_cycle_after_a_fill_plans_nothing(tmp_path: Path) -> None:
    """The fill converges once; it does not churn a patch every cycle."""
    a, b = (tmp_path / name for name in ("a", "b"))
    _write_record(a, "local_one", mtime_ns=100, cliSessionId="cli-a")
    _write_record(b, "local_one", mtime_ns=200, cliSessionId=None)
    first = build_registry_sync_plan(_scan(a, b), baselines=())
    for mutation in first.records["local_one.json"].mutations:
        apply_registry_mutation(first.scan, mutation)

    second = build_registry_sync_plan(_scan(a, b), baselines=first.proposed_baselines)

    assert not second.records["local_one.json"].mutations
    assert not any(
        item.group_name == "protected:cliSessionId" for item in second.conflicts
    )
    assert (
        json.loads((b / "local_one.json").read_text(encoding="utf-8"))["cliSessionId"]
        == "cli-a"
    )


def test_steady_state_conflicting_same_group_changes_are_quarantined(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100, title="Base")
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())

    for root, title in ((a, "A"), (b, "B")):
        path = root / "local_one.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["title"] = title
        path.write_text(json.dumps(record), encoding="utf-8")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=initial.proposed_baselines)

    conflict = next(item for item in plan.conflicts if item.group_name == "field:title")
    assert conflict.reason == "concurrent_divergence"
    assert "field:title" not in plan.records["local_one.json"].desired_groups


def test_missing_replica_is_create_only_from_composite(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Newest")
    c.mkdir()

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())
    record = plan.records["local_one.json"]

    assert len(record.mutations) == 2
    create = next(mutation for mutation in record.mutations if mutation.operation == "create")
    assert create.root_id == _root_id(plan.scan, c)
    assert json.loads(create.after_bytes)["title"] == "Newest"


def test_missing_replica_is_created_best_effort_when_a_group_conflicts(
    tmp_path: Path,
) -> None:
    # Until 2026-09-06 a missing replica was created only when NO group
    # conflicted, so a single undecidable field stranded the whole session in
    # one account.  The replica is now built from the decided composite plus
    # the newest extant copy's value for the undecidable group, which stays
    # quarantined: no baseline, conflict still recorded, extant copies untouched.
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=300, title="A", isArchived=True)
    _write_record(b, "local_one", mtime_ns=300, title="B", isArchived=True)
    c.mkdir()

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    conflict = next(item for item in plan.conflicts if item.group_name == "field:title")
    assert conflict.reason == "bootstrap_newest_tie"
    record = plan.records["local_one.json"]
    creates = [m for m in record.mutations if m.operation == "create"]
    assert [m.root_id for m in creates] == [_root_id(plan.scan, c)]
    created = json.loads(creates[0].after_bytes)
    assert created["isArchived"] is True
    assert created["title"] in {"A", "B"}
    assert "title" in creates[0].changed_fields
    assert "field:title" not in record.desired_groups
    assert not any(
        baseline.group_name == "field:title" for baseline in plan.proposed_baselines
    )
    # extant copies are never patched toward the best-effort seed
    assert all(m.operation == "create" for m in record.mutations)

    again = build_registry_sync_plan(_scan(a, b, c), baselines=())
    recreated = next(
        m for m in again.records["local_one.json"].mutations if m.operation == "create"
    )
    assert json.loads(recreated.after_bytes)["title"] == created["title"]


def test_unknown_key_does_not_block_replica_creation(tmp_path: Path) -> None:
    # The live 2026-09-06 defect: the desktop app began writing a key this
    # module had never classified (promptAppendSnapshot) on every new session
    # record, and every such session stayed missing from the other accounts
    # while verify_failed_files climbed one per session.
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, futureDesktopField={"append": "x"})
    b.mkdir()
    c.mkdir()

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    conflict = next(
        item for item in plan.conflicts if item.group_name == "unknown:futureDesktopField"
    )
    assert conflict.reason == "unknown_field_unclassified"
    record = plan.records["local_one.json"]
    creates = [m for m in record.mutations if m.operation == "create"]
    assert {m.root_id for m in creates} == {_root_id(plan.scan, b), _root_id(plan.scan, c)}
    for create in creates:
        created = json.loads(create.after_bytes)
        assert created["futureDesktopField"] == {"append": "x"}
        assert created["title"] == "Original"
        assert "futureDesktopField" in create.changed_fields
    assert "unknown:futureDesktopField" not in record.desired_groups
    assert not any(
        baseline.group_name == "unknown:futureDesktopField"
        for baseline in plan.proposed_baselines
    )

    for create in creates:
        apply_registry_mutation(plan.scan, create)
    assert verify_registry_sync_plan(plan, _scan(a, b, c)).verified

    second = build_registry_sync_plan(_scan(a, b, c), baselines=plan.proposed_baselines)
    assert not second.records["local_one.json"].mutations
    standing = next(
        item for item in second.conflicts if item.group_name == "unknown:futureDesktopField"
    )
    assert standing.reason == "unknown_field_unclassified"


def test_prompt_append_snapshot_and_scheduled_run_continued_are_classified(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(
        a,
        "local_one",
        mtime_ns=100,
        promptAppendSnapshot={"append": "x"},
        scheduledRunContinued=True,
    )
    b.mkdir()
    c.mkdir()

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    assert not plan.conflicts
    record = plan.records["local_one.json"]
    assert record.desired_groups["field:promptAppendSnapshot"]
    assert record.desired_groups["field:scheduledRunContinued"]
    creates = [m for m in record.mutations if m.operation == "create"]
    assert len(creates) == 2
    created = json.loads(creates[0].after_bytes)
    assert created["promptAppendSnapshot"] == {"append": "x"}
    assert created["scheduledRunContinued"] is True


def test_protected_cli_session_id_divergence_is_quarantined(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, cliSessionId="cli-a")
    _write_record(b, "local_one", mtime_ns=300, cliSessionId="cli-b")
    _write_record(c, "local_one", mtime_ns=200, cliSessionId="cli-a")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    conflict = next(
        item for item in plan.conflicts if item.group_name == "protected:cliSessionId"
    )
    assert conflict.reason == "protected_linkage_divergence"
    assert "protected:cliSessionId" not in plan.records["local_one.json"].desired_groups


def test_absent_cli_session_id_is_filled_from_the_one_copy_that_learned_it(
    tmp_path: Path,
) -> None:
    """REVERSED 2026-09-07; until then this asserted a quarantine.

    The old assertion was that a copy with no ``cliSessionId`` is just another
    distinct protected value, so the group quarantines.  That was the correct
    reading of "never clobber the app" right up until the 2026-09-07 measurement
    showed what it costs: both sync legs are create-only, so a record replicated
    while it is young keeps its empty pointer in every copy but the one whose
    account later ran it, and opening such a copy starts a fresh session instead
    of showing the transcript.  Fifteen of 4288 shared records were in that state.

    Filling an EMPTY pointer cannot clobber anything -- it reaches no transcript --
    which is what separates this from the divergence case pinned directly below.
    """
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, cliSessionId="cli-a")
    _write_record(b, "local_one", mtime_ns=300)
    _write_record(c, "local_one", mtime_ns=200, cliSessionId="cli-a")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    assert not any(
        item.group_name == "protected:cliSessionId" for item in plan.conflicts
    )
    desired = plan.records["local_one.json"].desired_groups["protected:cliSessionId"]
    assert json.loads(desired)["value"] == "cli-a"
    mutations = plan.records["local_one.json"].mutations
    assert {mutation.root_id for mutation in mutations} == {_root_id(plan.scan, b)}
    assert mutations[0].changed_fields["cliSessionId"] == {
        "state": "present",
        "value": "cli-a",
    }


def test_null_cli_session_id_is_filled_the_same_as_an_absent_one(
    tmp_path: Path,
) -> None:
    """The live failure writes an explicit null, not a missing key.

    A chip-spawned record is created with ``"cliSessionId": null``.  A fill rule
    that recognised only the absent form would read as working -- the test above
    would pass -- while never firing on the shape that actually occurs.
    """
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, cliSessionId="cli-a")
    _write_record(b, "local_one", mtime_ns=300, cliSessionId=None)
    _write_record(c, "local_one", mtime_ns=200, cliSessionId="cli-a")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    desired = plan.records["local_one.json"].desired_groups["protected:cliSessionId"]
    assert json.loads(desired)["value"] == "cli-a"
    assert {
        mutation.root_id for mutation in plan.records["local_one.json"].mutations
    } == {_root_id(plan.scan, b)}


def test_fill_never_merges_two_real_cli_session_ids(tmp_path: Path) -> None:
    """The quiet direction, and the whole reason the fill is narrow.

    Two non-null pointers mean the record was run independently under each
    account and each side legitimately has its own transcript.  An empty third
    copy must NOT be filled from either of them: there is no evidence here which
    one it belongs to, and writing either would assert a fork that is not ours to
    resolve.  ``claude_session_store_repair.py`` settles that case under a human,
    by comparing transcript lengths, which is evidence this module cannot see.
    """
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, cliSessionId="cli-a")
    _write_record(b, "local_one", mtime_ns=300, cliSessionId=None)
    _write_record(c, "local_one", mtime_ns=200, cliSessionId="cli-c")

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    conflict = next(
        item for item in plan.conflicts if item.group_name == "protected:cliSessionId"
    )
    assert conflict.reason == "protected_linkage_divergence"
    assert (
        "protected:cliSessionId"
        not in plan.records["local_one.json"].desired_groups
    )
    assert all(
        "cliSessionId" not in mutation.changed_fields
        for mutation in plan.records["local_one.json"].mutations
    )


def test_copies_that_all_lack_a_pointer_are_left_exactly_as_they_are(
    tmp_path: Path,
) -> None:
    """Absent is still distinct from null; the fill invents nothing.

    With no copy holding a pointer there is nothing to propagate, so the group
    stays quarantined rather than picking one empty encoding over the other.
    This is what remains true of the assertion this file used to make.
    """
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, cliSessionId=None)
    _write_record(b, "local_one", mtime_ns=300)
    _write_record(c, "local_one", mtime_ns=200, cliSessionId=None)

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    conflict = next(
        item for item in plan.conflicts if item.group_name == "protected:cliSessionId"
    )
    assert conflict.reason == "protected_linkage_divergence"
    assert all(
        "cliSessionId" not in mutation.changed_fields
        for mutation in plan.records["local_one.json"].mutations
    )


def test_unknown_future_key_is_quarantined_without_bootstrap_winner(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, futureDesktopField={"old": True})
    _write_record(b, "local_one", mtime_ns=300, futureDesktopField={"new": [1, 2]})
    _write_record(c, "local_one", mtime_ns=200)

    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    conflict = next(
        item
        for item in plan.conflicts
        if item.group_name == "unknown:futureDesktopField"
    )
    assert conflict.reason == "unknown_field_unclassified"
    assert set(conflict.candidates) == {
        _root_id(plan.scan, a),
        _root_id(plan.scan, b),
        _root_id(plan.scan, c),
    }
    assert "unknown:futureDesktopField" not in plan.records[
        "local_one.json"
    ].desired_groups
    assert not plan.records["local_one.json"].mutations


def test_apply_patch_requires_exact_expected_before_hash(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Winner")
    _write_record(c, "local_one", mtime_ns=200, title="Middle")
    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())
    mutation = next(
        item
        for item in plan.records["local_one.json"].mutations
        if item.root_id == _root_id(plan.scan, a)
    )
    path = a / "local_one.json"
    raced = json.loads(path.read_text(encoding="utf-8"))
    raced["isStarred"] = True
    path.write_text(json.dumps(raced), encoding="utf-8")

    with pytest.raises(RegistryMutationConflict, match="expected hash"):
        apply_registry_mutation(plan.scan, mutation)

    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "Old"
    assert json.loads(path.read_text(encoding="utf-8"))["isStarred"] is True


def test_apply_patch_preserves_fresh_unrelated_fields_when_hash_matches(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old", isStarred=True)
    _write_record(b, "local_one", mtime_ns=300, title="Winner", isStarred=True)
    _write_record(c, "local_one", mtime_ns=200, title="Middle", isStarred=True)
    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())
    mutation = next(
        item
        for item in plan.records["local_one.json"].mutations
        if item.root_id == _root_id(plan.scan, a)
    )

    result = apply_registry_mutation(plan.scan, mutation)

    assert result.applied
    record = json.loads((a / "local_one.json").read_text(encoding="utf-8"))
    assert record["title"] == "Winner"
    assert record["isStarred"] is True


def test_apply_create_is_create_only(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Winner")
    c.mkdir()
    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())
    mutation = next(
        item
        for item in plan.records["local_one.json"].mutations
        if item.operation == "create"
    )
    destination = c / "local_one.json"
    destination.write_text(
        json.dumps({"sessionId": "local_one", "title": "Desktop won"}),
        encoding="utf-8",
    )

    with pytest.raises(RegistryMutationConflict, match="already exists"):
        apply_registry_mutation(plan.scan, mutation)

    assert json.loads(destination.read_text(encoding="utf-8"))["title"] == "Desktop won"


def test_apply_create_publishes_complete_record(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Winner")
    c.mkdir()
    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())
    mutation = next(
        item
        for item in plan.records["local_one.json"].mutations
        if item.operation == "create"
    )

    result = apply_registry_mutation(plan.scan, mutation)

    assert result.applied
    assert json.loads((c / "local_one.json").read_text(encoding="utf-8"))[
        "title"
    ] == "Winner"
    assert not tuple(c.glob(".*.tmp-*"))


def test_verification_accepts_exact_intended_group_values(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Winner")
    _write_record(c, "local_one", mtime_ns=200, title="Middle")
    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    for mutation in plan.records["local_one.json"].mutations:
        root = plan.scan.roots[mutation.root_id].path
        (root / mutation.filename).write_text(mutation.after_bytes, encoding="utf-8")

    verification = verify_registry_sync_plan(plan, _scan(a, b, c))

    assert verification.verified
    assert not verification.failures


def test_verification_rejects_concurrent_change_to_intended_group(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Winner")
    _write_record(c, "local_one", mtime_ns=200, title="Middle")
    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())

    for mutation in plan.records["local_one.json"].mutations:
        root = plan.scan.roots[mutation.root_id].path
        (root / mutation.filename).write_text(mutation.after_bytes, encoding="utf-8")
    path = a / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["title"] = "Desktop raced"
    path.write_text(json.dumps(record), encoding="utf-8")

    verification = verify_registry_sync_plan(plan, _scan(a, b, c))

    assert not verification.verified
    failure = next(item for item in verification.failures if item.group_name == "field:title")
    assert failure.reason == "intended_value_mismatch"


def test_verification_requires_same_root_set(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100)
    plan = build_registry_sync_plan(_scan(a, b, c), baselines=())
    extra = tmp_path / "d"
    _write_record(extra, "local_one", mtime_ns=100)

    with pytest.raises(ValueError, match="root set"):
        verify_registry_sync_plan(plan, _scan(a, b, c, extra))


def test_second_cycle_after_convergence_is_byte_idempotent(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Winner")
    _write_record(c, "local_one", mtime_ns=200, title="Middle")
    first = build_registry_sync_plan(_scan(a, b, c), baselines=())
    for mutation in first.records["local_one.json"].mutations:
        root = first.scan.roots[mutation.root_id].path
        (root / mutation.filename).write_text(mutation.after_bytes, encoding="utf-8")

    second = build_registry_sync_plan(
        _scan(a, b, c), baselines=first.proposed_baselines
    )

    assert not second.records["local_one.json"].mutations
    assert not second.conflicts


def test_bootstrap_is_independent_of_root_arrival_order(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Winner")
    _write_record(c, "local_one", mtime_ns=200, title="Middle")

    forward = build_registry_sync_plan(_scan(a, b, c), baselines=())
    reverse = build_registry_sync_plan(_scan(c, b, a), baselines=())

    assert (
        forward.records["local_one.json"].desired_groups
        == reverse.records["local_one.json"].desired_groups
    )
    assert {
        (item.group_name, item.reason, tuple(sorted(item.candidates.values())))
        for item in forward.conflicts
    } == {
        (item.group_name, item.reason, tuple(sorted(item.candidates.values())))
        for item in reverse.conflicts
    }


def test_quarantined_protected_group_survives_later_cycles(tmp_path: Path) -> None:
    """A record whose cliSessionId stays quarantined must not poison later cycles.

    Quarantined groups never receive baselines, so a later steady-state cycle
    sees full baselines for every accepted group and none for the protected
    one.  That must read as a standing conflict, not a validation error, and
    the record's other groups must keep converging.
    """
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, cliSessionId="cli-a")
    _write_record(b, "local_one", mtime_ns=300, cliSessionId="cli-b")
    _write_record(c, "local_one", mtime_ns=200, cliSessionId="cli-a")
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())
    assert not any(
        baseline.group_name == "protected:cliSessionId"
        for baseline in initial.proposed_baselines
    )
    for mutation in initial.records["local_one.json"].mutations:
        root = initial.scan.roots[mutation.root_id].path
        (root / mutation.filename).write_text(mutation.after_bytes, encoding="utf-8")

    path = a / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["title"] = "Edited later"
    path.write_text(json.dumps(record), encoding="utf-8")

    plan = build_registry_sync_plan(
        _scan(a, b, c), baselines=initial.proposed_baselines
    )

    conflict = next(
        item for item in plan.conflicts if item.group_name == "protected:cliSessionId"
    )
    assert conflict.reason == "protected_linkage_divergence"
    desired = plan.records["local_one.json"].desired_groups["field:title"]
    assert json.loads(desired)["value"] == "Edited later"
    assert all(
        "cliSessionId" not in mutation.changed_fields
        for mutation in plan.records["local_one.json"].mutations
    )


def test_unaccepted_group_is_accepted_when_observations_collapse(
    tmp_path: Path,
) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=300, title="A")
    _write_record(b, "local_one", mtime_ns=300, title="B")
    _write_record(c, "local_one", mtime_ns=100, title="C")
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())
    tie = next(
        item for item in initial.conflicts if item.group_name == "field:title"
    )
    assert tie.reason == "bootstrap_newest_tie"

    for root in (a, b, c):
        path = root / "local_one.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["title"] = "Agreed"
        path.write_text(json.dumps(record), encoding="utf-8")

    plan = build_registry_sync_plan(
        _scan(a, b, c), baselines=initial.proposed_baselines
    )

    assert not any(item.group_name == "field:title" for item in plan.conflicts)
    desired = plan.records["local_one.json"].desired_groups["field:title"]
    assert json.loads(desired)["value"] == "Agreed"
    assert any(
        baseline.group_name == "field:title"
        for baseline in plan.proposed_baselines
    )


def test_unaccepted_group_divergence_never_reruns_newest_wins(
    tmp_path: Path,
) -> None:
    """After bootstrap, mtimes stop being conflict-resolution evidence."""
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=300, title="A")
    _write_record(b, "local_one", mtime_ns=300, title="B")
    _write_record(c, "local_one", mtime_ns=100, title="C")
    initial = build_registry_sync_plan(_scan(a, b, c), baselines=())

    path = a / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["title"] = "Newest by mtime"
    path.write_text(json.dumps(record), encoding="utf-8")
    os.utime(path, ns=(900, 900))

    plan = build_registry_sync_plan(
        _scan(a, b, c), baselines=initial.proposed_baselines
    )

    conflict = next(
        item for item in plan.conflicts if item.group_name == "field:title"
    )
    assert conflict.reason == "unaccepted_group_divergence"
    assert "field:title" not in plan.records["local_one.json"].desired_groups


def test_baseline_requires_every_root_and_group(tmp_path: Path) -> None:
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    for root in (a, b, c):
        _write_record(root, "local_one", mtime_ns=100)
    scan = _scan(a, b, c)
    incomplete = (
        RegistryBaseline(
            filename="local_one.json",
            root_id=_root_id(scan, a),
            group_name="field:title",
            value_json='{"state":"present","value":"Original"}',
            revision=1,
        ),
    )

    with pytest.raises(ValueError, match="incomplete baseline"):
        build_registry_sync_plan(scan, baselines=incomplete)


def test_scan_cache_reuses_unchanged_observations(tmp_path, monkeypatch) -> None:
    from session_bridge import desktop_registry as module
    from session_bridge.desktop_registry import RegistryScanCache

    a, b = tmp_path / "a", tmp_path / "b"
    _write_record(a, "local_one", mtime_ns=100, title="A")
    _write_record(b, "local_one", mtime_ns=200, title="B")

    reads: list[Path] = []
    original = module._stable_read

    def counting_stable_read(path: Path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(module, "_stable_read", counting_stable_read)

    cache = RegistryScanCache()
    first = scan_desktop_registry_roots((a, b), cache=cache)
    assert len(reads) == 2

    second = scan_desktop_registry_roots((a, b), cache=cache)
    assert len(reads) == 2  # no re-reads for unchanged files
    for filename, observations in first.records.items():
        for root_id, observation in observations.items():
            assert second.records[filename][root_id] is observation


def test_scan_cache_rereads_changed_files_and_evicts_deleted(
    tmp_path,
) -> None:
    from session_bridge.desktop_registry import RegistryScanCache

    a, b = tmp_path / "a", tmp_path / "b"
    _write_record(a, "local_one", mtime_ns=100, title="A")
    _write_record(b, "local_one", mtime_ns=200, title="B")
    _write_record(a, "local_two", mtime_ns=100)
    _write_record(b, "local_two", mtime_ns=100)

    cache = RegistryScanCache()
    scan_desktop_registry_roots((a, b), cache=cache)

    path = a / "local_one.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["title"] = "Changed"
    path.write_text(json.dumps(record), encoding="utf-8")
    os.utime(path, ns=(300, 300))
    (a / "local_two.json").unlink()
    (b / "local_two.json").unlink()

    fresh = scan_desktop_registry_roots((a, b), cache=cache)

    changed = next(
        observation
        for observation in fresh.records["local_one.json"].values()
        if observation.path == path
    )
    assert json.loads(changed.exact_bytes)["title"] == "Changed"
    assert "local_two.json" not in fresh.records
    assert all("local_two" not in key for key in cache.entries)


def test_scan_cache_produces_identical_plans(tmp_path) -> None:
    from session_bridge.desktop_registry import RegistryScanCache

    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    _write_record(a, "local_one", mtime_ns=100, title="Old")
    _write_record(b, "local_one", mtime_ns=300, title="Newest")
    _write_record(c, "local_one", mtime_ns=200, title="Middle")

    cache = RegistryScanCache()
    cached = build_registry_sync_plan(
        scan_desktop_registry_roots((a, b, c), cache=cache), baselines=()
    )
    uncached = build_registry_sync_plan(
        scan_desktop_registry_roots((a, b, c)), baselines=()
    )

    assert (
        cached.records["local_one.json"].desired_groups
        == uncached.records["local_one.json"].desired_groups
    )
    assert len(cached.records["local_one.json"].mutations) == len(
        uncached.records["local_one.json"].mutations
    )
