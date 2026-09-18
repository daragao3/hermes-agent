"""``hermes_cli.kanban_db`` must not walk the tool registry at import.

Why this exists
---------------
``KNOWN_TOOLSET_NAMES = frozenset(... get_toolset_names())`` used to run at
module import. ``get_toolset_names()`` reaches ``tools.registry`` -- tool
discovery -- so every importer of the kanban DB layer (the dispatcher, the
dashboard, and until 2f84799b81 the test suite's own autouse conftest fixture)
paid tool discovery at startup for a check only ``_normalize_task_skills``
makes. It is now ``_known_toolset_names()``, resolved on first use and
memoized (loops kanban-db-known-toolset-names-lazy-20260918).

The import assertion runs in a SUBPROCESS on purpose: ``sys.modules`` is
process-global, so a sibling test that legitimately imported the registry
would mask a regression here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_importing_kanban_db_does_not_load_the_tool_registry():
    code = (
        "import sys; import hermes_cli.kanban_db; "
        "print('tools.registry' in sys.modules)"
    )
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), HERMES_DISABLE_LAZY_INSTALLS="1")
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env,
        cwd=str(REPO_ROOT), timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False", (
        "importing hermes_cli.kanban_db loaded tools.registry -- tool discovery "
        "is back on every importer's startup path"
    )


def test_known_toolset_names_is_resolved_once_on_first_use(monkeypatch):
    from hermes_cli import kanban_db

    calls = []

    def _fake_names():
        calls.append(1)
        return ["Browser", "terminal"]

    monkeypatch.setattr(kanban_db, "get_toolset_names", _fake_names)
    monkeypatch.setattr(kanban_db, "_known_toolset_names_memo", None)

    assert calls == [], "the names must not be resolved before first use"
    first = kanban_db._known_toolset_names()
    second = kanban_db._known_toolset_names()
    assert first == frozenset({"browser", "terminal"})
    assert second is first
    assert calls == [1], "get_toolset_names must run exactly once"


def test_normalize_task_skills_rejects_toolset_names_case_insensitively(monkeypatch):
    from hermes_cli import kanban_db

    monkeypatch.setattr(kanban_db, "get_toolset_names", lambda: ["browser", "terminal"])
    monkeypatch.setattr(kanban_db, "_known_toolset_names_memo", None)

    assert kanban_db._normalize_task_skills(["my-skill", " my-skill ", "other"]) == [
        "my-skill", "other",
    ]
    with pytest.raises(ValueError, match="toolset name"):
        kanban_db._normalize_task_skills(["my-skill", "Browser", "TERMINAL"])
