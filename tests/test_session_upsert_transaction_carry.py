"""Test the lifecycle SQL writer without opening a production SessionDB."""
import json
import sqlite3

import pytest

from hermes_state_common import SCHEMA_SQL
from hermes_state_sessions import SessionSessionsMixin


class Rows(SessionSessionsMixin):
    def _own_profile_name(self):
        return None

    def _store_system_prompt(self, conn, prompt):
        assert prompt is None  # Prompt storage remains the facade's responsibility.
        return None


class TransactionalRows(Rows):
    _TRANSCRIPT_WRITE_PATIENCE_S = 17

    def __init__(self, conn):
        self.conn = conn

    def _execute_write(self, fn, *, patience_s=None):
        with self.conn:
            return fn(self.conn)

    def _write_rowcount(self, sql, params):
        return self._execute_write(lambda conn: conn.execute(sql, params).rowcount)


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA_SQL)
    yield db
    db.close()


def test_caller_rollback_removes_row_and_keeps_transaction_open(conn):
    conn.execute("BEGIN")
    Rows()._upsert_session_row(conn, "s", "codex", started_at=123.5)
    assert conn.in_transaction
    assert conn.execute("SELECT started_at FROM sessions").fetchone()[0] == 123.5
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_placeholder_enrichment_retains_real_identity_and_first_timestamp(conn):
    rows = Rows()
    rows._upsert_session_row(conn, "s", " UNKNOWN ", started_at=0)
    rows._upsert_session_row(conn, "s", " cli ", model="first", model_config={"a": 1})
    rows._upsert_session_row(conn, "s", "codex", model="later", model_config={"a": 2})
    row = conn.execute("SELECT * FROM sessions").fetchone()
    assert (row["source"], row["model"], row["started_at"]) == ("cli", "first", 0)
    assert json.loads(row["model_config"]) == {"a": 1}


def test_ensure_session_preserves_local_enrichment_contract(conn):
    rows = TransactionalRows(conn)
    assert rows.ensure_session('s') == 's'
    first_started = conn.execute('SELECT started_at FROM sessions').fetchone()[0]
    assert rows.ensure_session('s', source='cli', model='first', model_config={'setting': 1}) == 's'
    assert rows.ensure_session('s', source='codex', model='later', model_config={'setting': 2}) == 's'
    stored = conn.execute('SELECT * FROM sessions').fetchone()
    assert stored['source'] == 'cli'
    assert stored['model'] == 'first'
    assert json.loads(stored['model_config']) == {'setting': 1}
    assert stored['started_at'] == first_started
    assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1


def test_same_cwd_probe_failure_preserves_captured_git_metadata(conn):
    rows = TransactionalRows(conn)
    rows.ensure_session('s', source='cli', cwd='A')
    first = rows.update_session_cwd('s', 'A', git_branch=' main ', git_repo_root=' repo-a ')
    second = rows.update_session_cwd('s', 'A')
    stored = conn.execute('SELECT cwd,git_branch,git_repo_root,git_metadata_generation FROM sessions').fetchone()
    assert tuple(stored) == ('A', 'main', 'repo-a', second)
    assert second == first + 1


def test_workspace_move_clears_old_git_identity_and_rejects_stale_aba_probe(conn):
    rows = TransactionalRows(conn)
    rows.ensure_session('s', source='cli', cwd='A')
    first = rows.update_session_cwd('s', 'A', git_branch='main', git_repo_root='repo-a')
    middle = rows.update_session_cwd('s', 'B')
    assert tuple(conn.execute('SELECT cwd,git_branch,git_repo_root FROM sessions').fetchone()) == ('B', None, None)
    latest = rows.update_session_cwd('s', 'A')
    assert first < middle < latest
    assert rows.publish_session_git_metadata('s', 'A', first, git_branch='stale', git_repo_root='wrong') is False
    assert rows.publish_session_git_metadata('s', 'A', latest, git_branch='current', git_repo_root='repo-a') is True
    assert tuple(conn.execute('SELECT git_branch,git_repo_root FROM sessions').fetchone()) == ('current', 'repo-a')


def test_explicit_git_replacement_can_clear_metadata_without_cwd_change(conn):
    rows = TransactionalRows(conn)
    rows.ensure_session('s', source='cli', cwd='A')
    rows.update_session_cwd('s', 'A', git_branch='main', git_repo_root='repo-a')
    rows.update_session_cwd('s', 'A', replace_git_meta=True)
    assert tuple(conn.execute('SELECT cwd,git_branch,git_repo_root FROM sessions').fetchone()) == ('A', None, None)


def test_cwd_update_does_not_create_missing_sessions(conn):
    rows = TransactionalRows(conn)
    assert rows.update_session_cwd('missing', 'A') is None
    assert rows.update_session_cwd('', 'A') is None
    assert rows.update_session_cwd('missing', '') is None
    assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0


def test_upstream_reset_marker_survives_config_enrichment(conn):
    rows = Rows()
    rows._upsert_session_row(conn, "s", "cli", model_config={"_reset_from": "p"})
    rows._upsert_session_row(conn, "s", "cli", model_config={"model": "new"})
    assert json.loads(conn.execute("SELECT model_config FROM sessions").fetchone()[0]) == {
        "_reset_from": "p", "model": "new",
    }


def test_public_writer_keeps_patience_and_forwards_metadata(conn):
    class Writer(Rows):
        _TRANSCRIPT_WRITE_PATIENCE_S = 17

        def _execute_write(self, fn, *, patience_s):
            assert patience_s == 17
            with conn:
                fn(conn)

    Writer()._insert_session_row(
        "s", "cli", session_key="key", chat_id="chat", chat_type="private",
        thread_id="thread", git_repo_root="repo", origin_json='{"driver":"codex"}',
        display_name="name", cwd="explicit", profile_name="profile",
    )
    row = conn.execute("SELECT * FROM sessions").fetchone()
    for key, expected in {
        "session_key": "key", "chat_id": "chat", "chat_type": "private", "thread_id": "thread",
        "git_repo_root": "repo", "origin_json": '{"driver":"codex"}', "display_name": "name",
        "cwd": "explicit", "profile_name": "profile",
    }.items():
        assert row[key] == expected
    assert not conn.in_transaction


@pytest.mark.parametrize("source,parent_source,cwd_kind,explicit,expected", [
    ("cli", "cli", "absolute", None, True),
    ("tui", "cli", "absolute", None, False),
    ("cli", "telegram", "absolute", None, False),
    ("cli", "cli", "relative", None, False),
    ("cli", "cli", "absolute", "other", False),
])
def test_local_child_workspace_inheritance(conn, tmp_path, source, parent_source, cwd_kind, explicit, expected):
    rows = Rows()
    cwd = str(tmp_path / "parent") if cwd_kind == "absolute" else "relative"
    rows._upsert_session_row(conn, "parent", parent_source, cwd=cwd, git_repo_root="repo")
    conn.execute("UPDATE sessions SET git_branch='branch' WHERE id='parent'")
    child_cwd = str(tmp_path / "other") if explicit else None
    rows._upsert_session_row(conn, "child", source, parent_session_id="parent", cwd=child_cwd)
    row = conn.execute("SELECT cwd, git_repo_root, git_branch FROM sessions WHERE id='child'").fetchone()
    assert row["cwd"] == (child_cwd or (cwd if expected else None))
    assert (row["git_repo_root"], row["git_branch"]) == (("repo", "branch") if expected else (None, None))


@pytest.mark.parametrize("compression", [True, False])
def test_remote_profile_and_routing_inheritance_remain_upstream(conn, compression):
    rows = Rows()
    rows._upsert_session_row(conn, "parent", "telegram", cwd="/remote/workspace", profile_name="parent",
                             session_key="agent:a:chat", chat_id="chat", git_repo_root="/remote/repo")
    if compression:
        conn.execute("UPDATE sessions SET end_reason='compression' WHERE id='parent'")
    rows._upsert_session_row(conn, "child", "telegram", parent_session_id="parent", session_key="agent:b:other")
    row = conn.execute("SELECT cwd, git_repo_root, profile_name, chat_id FROM sessions WHERE id='child'").fetchone()
    assert tuple(row) == ("/remote/workspace", "/remote/repo", None, "chat" if compression else None)


def test_explicit_repository_does_not_receive_parent_branch(conn, tmp_path):
    rows = Rows()
    cwd = str(tmp_path)
    rows._upsert_session_row(conn, "parent", "cli", cwd=cwd, git_repo_root="parent-repo")
    conn.execute("UPDATE sessions SET git_branch='parent-branch' WHERE id='parent'")
    rows._upsert_session_row(conn, "child", "cli", cwd=cwd, git_repo_root="child-repo", parent_session_id="parent")
    row = conn.execute("SELECT git_repo_root, git_branch FROM sessions WHERE id='child'").fetchone()
    assert tuple(row) == ("child-repo", None)
