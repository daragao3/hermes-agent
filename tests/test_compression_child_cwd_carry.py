"""Exercise the real compression child SQL writer against the bundled schema."""
import sqlite3
from types import SimpleNamespace

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_compression import SessionCompressionMixin


@pytest.mark.parametrize("parent_source,child_source,cwd_kind,identity,expected", [
    ("cli", "cli", "absolute", "parent", True),
    ("tui", "tui", "absolute", "parent", True),
    ("cli", "tui", "absolute", "parent", False),
    ("telegram", "telegram", "absolute", "parent", False),
    ("cli", "cli", "relative", "parent", False),
    ("cli", "cli", "absolute", "other", False),
    ("cli", "cli", "whitespace", "parent", False),
    ("cli", "cli", "missing", "parent", False),
])
def test_compression_inherits_only_authoritative_local_parent_cwd(
    tmp_path, parent_source, child_source, cwd_kind, identity, expected,
):
    cwd = {"absolute": str(tmp_path / "project"), "relative": "relative/project",
           "whitespace": " " + str(tmp_path / "project"), "missing": None}[cwd_kind]
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO sessions(id, source, cwd, started_at) VALUES (?, ?, ?, 0)",
                     (identity, parent_source, cwd))
        conn.execute("UPDATE sessions SET git_repo_root='repo', git_branch='branch'")
        parent = conn.execute("SELECT * FROM sessions WHERE id = ?", (identity,)).fetchone()
        db = SimpleNamespace(_store_system_prompt=lambda conn, prompt: None, _own_profile_name=lambda: "test")
        SessionCompressionMixin._publish_child_session_row(
            db, conn, parent, parent_session_id="parent", child_session_id="child",
            source=child_source, model="test", model_config=None, system_prompt=None,
            cwd=None, profile_name=None,
        )
        child = conn.execute("SELECT cwd, source, git_repo_root, git_branch FROM sessions WHERE id = 'child'").fetchone()
        assert child["cwd"] == (cwd if expected else None)
        assert child["source"] == child_source
        assert (child["git_repo_root"], child["git_branch"]) == (("repo", "branch") if expected else (None, None))


@pytest.mark.parametrize("child_cwd,keep_git", [(None, True), ("same", True), ("other", False)])
def test_compression_git_metadata_tracks_selected_cwd(tmp_path, child_cwd, keep_git):
    parent_cwd = str(tmp_path / "parent")
    explicit = parent_cwd if child_cwd == "same" else str(tmp_path / "other") if child_cwd else None
    conn = sqlite3.connect(":memory:")
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT INTO sessions(id, source, cwd, git_repo_root, git_branch, started_at) "
                     "VALUES ('parent', 'cli', ?, 'repo', 'branch', 0)", (parent_cwd,))
        parent = conn.execute("SELECT * FROM sessions").fetchone()
        db = SimpleNamespace(_store_system_prompt=lambda conn, prompt: None, _own_profile_name=lambda: None)
        SessionCompressionMixin._publish_child_session_row(
            db, conn, parent, parent_session_id="parent", child_session_id="child", source="cli",
            model=None, model_config=None, system_prompt=None, cwd=explicit, profile_name=None,
        )
        row = conn.execute("SELECT git_repo_root, git_branch FROM sessions WHERE id='child'").fetchone()
        assert tuple(row) == (("repo", "branch") if keep_git else (None, None))
    finally:
        conn.close()
