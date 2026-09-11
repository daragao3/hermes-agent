from __future__ import annotations

import json
from pathlib import Path

import pytest

from session_bridge.desktop_presentation import (
    PresentationConflict,
    PresentationMutationConflict,
    apply_presentation_mutation,
    build_presentation_plan,
    scan_presentation_roots,
    verify_presentation_plan,
)


def _config(starred: list[str], order: list[str] | None = None, **extra) -> dict:
    order = starred if order is None else order
    return {
        "preferences": {
            "unrelated": {"keep": True},
            "epitaxyPrefs": {
                "starred-local-code-sessions": starred,
                "dframe-local-slice": {
                    "pinnedOrder": [f"code:{session_id}" for session_id in order],
                    "homeProjectsPinnedOrder": [],
                },
            },
        },
        **extra,
    }


def _write_root(
    root: Path,
    starred: list[str],
    *,
    order: list[str] | None = None,
    session_ids: list[str] | None = None,
    archived_ids: tuple[str, ...] = (),
) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    config = root / "claude_desktop_config.json"
    config.write_text(json.dumps(_config(starred, order)), encoding="utf-8")
    sessions = root / "sessions"
    sessions.mkdir()
    for session_id in session_ids if session_ids is not None else starred:
        (sessions / f"{session_id}.json").write_text(
            json.dumps(
                {"sessionId": session_id, "isArchived": session_id in archived_ids}
            ),
            encoding="utf-8",
        )
    return config, sessions


def _scan(*roots: tuple[Path, Path]):
    return scan_presentation_roots(
        [(f"root-{index}", config, sessions) for index, (config, sessions) in enumerate(roots)]
    )


def test_bootstrap_uses_unique_nonempty_presentation_and_defers_live_root(tmp_path: Path) -> None:
    source = _write_root(tmp_path / "source", ["local_a", "local_b"], order=["local_b", "local_a"])
    target = _write_root(
        tmp_path / "target", [], session_ids=["local_a", "local_b"]
    )

    plan = build_presentation_plan(
        _scan(source, target), baselines={}, active_root_id="root-1"
    )

    assert plan.desired.starred == ("local_a", "local_b")
    assert plan.desired.pinned_order == ("code:local_b", "code:local_a")
    assert plan.mutations == ()
    assert plan.pending_active_roots == ("root-1",)
    assert not plan.conflicts


def test_bootstrap_patches_dormant_empty_root_and_preserves_unrelated_config(tmp_path: Path) -> None:
    source = _write_root(tmp_path / "source", ["local_a"])
    target = _write_root(tmp_path / "target", [], session_ids=["local_a"])
    scan = _scan(source, target)
    plan = build_presentation_plan(scan, baselines={}, active_root_id="root-0")

    assert len(plan.mutations) == 1
    result = apply_presentation_mutation(scan, plan.mutations[0])
    assert result.applied
    written = json.loads(target[0].read_text(encoding="utf-8"))
    assert written["preferences"]["unrelated"] == {"keep": True}
    epitaxy = written["preferences"]["epitaxyPrefs"]
    assert epitaxy["starred-local-code-sessions"] == ["local_a"]
    assert epitaxy["dframe-local-slice"]["pinnedOrder"] == []
    assert verify_presentation_plan(plan, _scan(source, target)).ok


def test_pinned_order_is_app_local_and_can_differ_from_visible_pins(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path / "root",
        ["local_a", "local_b"],
        order=[],
    )

    observed = _scan(root).roots["root-0"].state

    assert observed.starred == ("local_a", "local_b")
    assert observed.pinned_order == ()


def test_non_code_pinned_order_entry_fails_closed(tmp_path: Path) -> None:
    root = _write_root(tmp_path / "root", ["local_a"])
    document = json.loads(root[0].read_text(encoding="utf-8"))
    document["preferences"]["epitaxyPrefs"]["dframe-local-slice"][
        "pinnedOrder"
    ] = ["space:not-code"]
    root[0].write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(PresentationConflict, match="non-Code"):
        _scan(root)


def test_archived_star_is_filtered_from_visible_canonical_state(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path / "root",
        ["local_visible", "local_archived"],
        session_ids=["local_visible", "local_archived"],
        archived_ids=("local_archived",),
    )

    observed = _scan(root).roots["root-0"].state

    assert observed.starred == ("local_visible",)


def test_unknown_session_reference_fails_closed(tmp_path: Path) -> None:
    root = _write_root(
        tmp_path / "root", ["local_a", "local_missing"], session_ids=["local_a"]
    )

    with pytest.raises(PresentationConflict, match="unknown session"):
        _scan(root)


def test_single_sided_pin_unpin_and_reorder_propagate_after_baseline(tmp_path: Path) -> None:
    a = _write_root(tmp_path / "a", ["local_a"], session_ids=["local_a", "local_b"])
    b = _write_root(tmp_path / "b", ["local_a"], session_ids=["local_a", "local_b"])
    initial = _scan(a, b)
    baseline = {root_id: root.state.canonical for root_id, root in initial.roots.items()}

    a[0].write_text(
        json.dumps(_config(["local_a", "local_b"], order=["local_b", "local_a"])),
        encoding="utf-8",
    )
    plan = build_presentation_plan(
        _scan(a, b), baselines=baseline, active_root_id="root-0"
    )
    assert len(plan.mutations) == 1
    assert plan.mutations[0].root_id == "root-1"
    apply_presentation_mutation(plan.scan, plan.mutations[0])

    converged = _scan(a, b)
    baseline = {root_id: root.state.canonical for root_id, root in converged.roots.items()}
    a[0].write_text(json.dumps(_config([], order=[])), encoding="utf-8")
    plan = build_presentation_plan(
        _scan(a, b), baselines=baseline, active_root_id="root-0"
    )
    assert len(plan.mutations) == 1
    assert plan.desired.starred == ()


def test_new_root_is_adopted_from_converged_existing_baselines(tmp_path: Path) -> None:
    a = _write_root(tmp_path / "a", ["local_a"], session_ids=["local_a"])
    b = _write_root(tmp_path / "b", ["local_a"], session_ids=["local_a"])
    initial = _scan(a, b)
    baseline = {root_id: root.state.canonical for root_id, root in initial.roots.items()}
    c = _write_root(tmp_path / "c", [], session_ids=["local_a"])

    plan = build_presentation_plan(
        _scan(a, b, c), baselines=baseline, active_root_id="root-0"
    )

    assert plan.desired.starred == ("local_a",)
    assert len(plan.mutations) == 1
    assert plan.mutations[0].root_id == "root-2"


def test_disappeared_baselined_root_fails_closed(tmp_path: Path) -> None:
    a = _write_root(tmp_path / "a", ["local_a"], session_ids=["local_a"])
    b = _write_root(tmp_path / "b", ["local_a"], session_ids=["local_a"])
    initial = _scan(a, b)
    baseline = {root_id: root.state.canonical for root_id, root in initial.roots.items()}

    with pytest.raises(PresentationConflict, match="disappeared"):
        build_presentation_plan(
            _scan(a), baselines=baseline, active_root_id="root-0"
        )


def test_concurrent_divergence_is_quarantined(tmp_path: Path) -> None:
    ids = ["local_a", "local_b", "local_c"]
    a = _write_root(tmp_path / "a", ["local_a"], session_ids=ids)
    b = _write_root(tmp_path / "b", ["local_a"], session_ids=ids)
    initial = _scan(a, b)
    baseline = {root_id: root.state.canonical for root_id, root in initial.roots.items()}
    a[0].write_text(json.dumps(_config(["local_a", "local_b"])), encoding="utf-8")
    b[0].write_text(json.dumps(_config(["local_a", "local_c"])), encoding="utf-8")

    plan = build_presentation_plan(
        _scan(a, b), baselines=baseline, active_root_id=None
    )

    assert plan.mutations == ()
    assert plan.desired is None
    assert plan.conflicts == ("concurrent_divergence",)


def test_patch_refuses_hash_race(tmp_path: Path) -> None:
    source = _write_root(tmp_path / "source", ["local_a"])
    target = _write_root(tmp_path / "target", [], session_ids=["local_a"])
    scan = _scan(source, target)
    plan = build_presentation_plan(scan, baselines={}, active_root_id="root-0")
    raced = json.loads(target[0].read_text(encoding="utf-8"))
    raced["preferences"]["new-setting"] = True
    target[0].write_text(json.dumps(raced), encoding="utf-8")

    with pytest.raises(PresentationMutationConflict, match="expected hash"):
        apply_presentation_mutation(scan, plan.mutations[0])

    assert json.loads(target[0].read_text(encoding="utf-8"))["preferences"]["new-setting"] is True
