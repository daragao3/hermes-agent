"""Real bridge adapter/export against an in-process GBrain CLI transport."""
import json
import subprocess
from unittest.mock import Mock

import pytest

from plugins.memory.honcho import bridge


def test_export_conflict_preserves_competitor_and_retries_only_compiled(tmp_path, monkeypatch):
    page = dict(slug="people/example", source_id="default", revision=4,
                type="person", title="Example", frontmatter={"custom": "kept"},
                tags=["kept"], compiled_truth="Original", timeline="Old event")
    writes = []
    timeline = []
    conflict = True

    def transport(argv, **kwargs):
        nonlocal conflict
        if argv[1] == "timeline-add":
            timeline.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")
        assert argv[1] == "call", "unconditional CLI writer must never run"
        tool, payload = argv[-2], json.loads(argv[-1])
        if tool == "get_page":
            result = dict(page)
        else:
            assert tool == "put_page_conditional"
            assert argv[2:4] == ["--source", "default"]
            assert payload["mode"] == "compare_and_swap"
            writes.append(payload)
            if conflict:
                page.update(revision=5, compiled_truth="Concurrent writer's fact")
                conflict = False
            if payload["expected_revision"] != page["revision"]:
                result = {"status": "conflict", "slug": page["slug"]}
            else:
                assert "Concurrent writer's fact" in payload["content"]
                assert "custom: kept" in payload["content"]
                assert "Old event" in payload["content"]
                result = {"status": "updated", "slug": page["slug"], "revision": 6}
        return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")

    monkeypatch.setattr(bridge, "run_text_capture", transport)
    honcho = Mock()
    honcho.read_user_facts.return_value = ["New fact"]
    state = tmp_path / "state.json"
    args = dict(slug=page["slug"], date="2026-09-10", dialectic_queries=[],
                state_path=state, dry_run=False)
    bridge.run_export(honcho, bridge.GBrainAdapter(), **args)
    assert page["compiled_truth"] == "Concurrent writer's fact"
    assert not bridge.load_state(bridge._compiled_state_path(state))
    bridge.run_export(honcho, bridge.GBrainAdapter(), **args)
    assert len(timeline) == 1
    assert [w["expected_revision"] for w in writes] == [4, 5]
    assert bridge.fact_hash("New fact") in bridge.load_state(bridge._compiled_state_path(state))


def test_write_without_snapshot_never_invokes_cli(monkeypatch):
    run = Mock()
    monkeypatch.setattr(bridge, "run_text_capture", run)
    assert bridge.GBrainAdapter().put_page("people/example", "changed") is False
    run.assert_not_called()


@pytest.mark.parametrize("result", [
    {"status": "conflict"}, {"status": "error"},
    {"status": "updated", "slug": "wrong", "revision": 6},
    {"status": "updated", "slug": "people/example", "revision": True},
    {"status": "updated", "slug": "people/example", "revision": 2},
    [],
])
def test_zero_exit_does_not_accept_refusal_or_malformed_write(result, monkeypatch):
    monkeypatch.setattr(bridge, "run_text_capture", lambda argv, **kw:
                        subprocess.CompletedProcess(argv, 0, json.dumps(result), ""))
    snapshot = bridge._PageSnapshot("old", "people/example", "default", 4)
    assert bridge.GBrainAdapter().put_page("people/example", "changed", snapshot=snapshot) is False


@pytest.mark.parametrize("changes", [
    {"revision": True}, {"revision": 0}, {"revision": "4"},
    {"source_id": None}, {"slug": "different"}, {"frontmatter": ["invalid"]},
])
def test_unbound_or_malformed_read_cannot_authorize_write(changes, monkeypatch):
    page = dict(slug="people/example", source_id="default", revision=4,
                compiled_truth="Original", timeline="", frontmatter={})
    page.update(changes)
    monkeypatch.setattr(bridge, "run_text_capture", lambda argv, **kw:
                        subprocess.CompletedProcess(argv, 0, json.dumps(page), ""))
    assert bridge.GBrainAdapter().get_page("people/example") is None
