"""Regression tests for the plugin-compat pointer detector.

The string-target branch of this checker was DEAD CODE from the day it was
written, and nothing noticed because a checker that finds nothing and a checker
that cannot find anything print the same thing. ``str_pat`` required quote
characters but was ``fullmatch``ed against ``ast.Constant.value``, which is the
string's *value* -- the quotes are syntax and are gone by then. So
``patch("facade.name")``, the shape the script's own docstring advertises and the
most common one in this test suite, never matched.

The lesson these tests exist to lock: a detector needs a case that MUST fire, not
only cases that must not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.check_compat_pointers as ccp

_MANIFEST = {
    "schema": 1,
    "note": "test fixture",
    "entries": [
        {"facade": "run_agent", "name": "OpenAI", "kind": "moved-lazy",
         "target": "agent.process_bootstrap"},
        {"facade": "hermes_cli.kanban_db", "name": "connect", "kind": "moved-lazy",
         "target": "hermes_cli.kanban_db_connect"},
    ],
}


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the checker at a throwaway tree with a two-entry manifest."""
    manifest = tmp_path / "compat_manifest.json"
    manifest.write_text(json.dumps(_MANIFEST), encoding="utf-8")
    monkeypatch.setattr(ccp, "ROOT", tmp_path)
    monkeypatch.setattr(ccp, "MANIFEST", manifest)
    return tmp_path


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.lstrip("\n"), encoding="utf-8")


def _run(capsys) -> tuple[int, str]:
    rc = ccp.main()
    return rc, capsys.readouterr().out


def test_string_patch_target_is_flagged(tree: Path, capsys) -> None:
    """THE REGRESSION. Before the fix this returned 0 and printed the all-clear."""
    _write(tree, "tests/test_thing.py", '''
from unittest.mock import patch

def test_x():
    with patch("run_agent.OpenAI"):
        pass
''')
    rc, out = _run(capsys)
    assert rc == 1, f"string patch target not detected:\n{out}"
    assert "run_agent.OpenAI" in out


def test_string_target_for_a_dotted_facade_is_flagged(tree: Path, capsys) -> None:
    """The facade itself may be dotted; rpartition must split on the LAST dot."""
    _write(tree, "tests/test_kanban.py", '''
from unittest.mock import patch
patch("hermes_cli.kanban_db.connect")
''')
    rc, out = _run(capsys)
    assert rc == 1, out
    assert "hermes_cli.kanban_db.connect" in out


def test_unrelated_dotted_string_is_not_flagged(tree: Path, capsys) -> None:
    _write(tree, "tests/test_other.py", '''
x = "os.path.join"
y = "run_agent.something_that_never_moved"
''')
    rc, out = _run(capsys)
    assert rc == 0, out


def test_prose_mentioning_a_pointer_is_not_flagged(tree: Path, capsys) -> None:
    """``fullmatch`` is load-bearing: a docstring naming the path is not a use."""
    _write(tree, "tests/test_prose.py", '''
"""We used to patch run_agent.OpenAI here; see COMPAT_MANIFEST.md."""
z = "the old path was run_agent.OpenAI"
''')
    rc, out = _run(capsys)
    assert rc == 0, out


def test_worktrees_under_dot_claude_are_skipped(tree: Path, capsys) -> None:
    """This repo's per-session worktrees live at ``.claude/worktrees/<name>``.

    Without ``.claude`` in SKIP_DIRS the walk covers every sibling checkout --
    it never finished, and it would report other sessions' files as ours.
    """
    _write(tree, ".claude/worktrees/sibling/tests/test_thing.py", '''
from unittest.mock import patch
patch("run_agent.OpenAI")
''')
    rc, out = _run(capsys)
    assert rc == 0, f"scanned a sibling worktree:\n{out}"
