"""Kanban worker runs must not surface as user conversations.

Workers spawn as `hermes chat -q "work kanban task <id>"`, which used to land in
state.db as an untitled `cli` row — the desktop sidebar then rendered one entry
per attempt, labeled with the worker's own prompt.
"""

import os
import sqlite3

import pytest

from hermes_state import SessionDB


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    database = SessionDB(db_path=tmp_path / "state.db")
    yield database
    database.close()


def test_worker_spawn_tags_session_source_kanban(monkeypatch, tmp_path):
    """The dispatcher tags the worker's env so its session is a `kanban` row."""
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as kbd

    captured = {}

    class _Proc:
        pid = 4321

    def _fake_popen(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return _Proc()

    monkeypatch.setattr("subprocess.Popen", _fake_popen)
    monkeypatch.setattr(kbd, "_retag_legacy_worker_sessions", lambda _root: None)
    monkeypatch.setattr(kb, "worker_logs_dir", lambda board=None: tmp_path / "logs")

    task = kb.Task(
        id="t_b21733fb",
        title="ship it",
        body=None,
        assignee="default",
        status="in_progress",
        priority=0,
        created_by=None,
        created_at=0,
        started_at=None,
        completed_at=None,
        workspace_kind="scratch",
        workspace_path=None,
        claim_lock=None,
        claim_expires=None,
        tenant=None,
    )
    workspace = str(tmp_path / "ws")
    os.makedirs(workspace, exist_ok=True)

    kbd._default_spawn(task, workspace)

    assert captured["env"]["HERMES_SESSION_SOURCE"] == "kanban"


def test_kanban_rows_stay_out_of_the_session_list(db):
    """A `kanban` row is filtered by the same exclude the sidebar sends."""
    db.create_session(session_id="chat", source="desktop")
    db.append_message(session_id="chat", role="user", content="hey")
    db.create_session(session_id="worker", source="kanban")
    db.append_message(session_id="worker", role="user", content="work kanban task t_b21733fb")

    listed = db.list_sessions_rich(exclude_sources=["cron", "kanban", "subagent", "tool"])

    assert [row["id"] for row in listed] == ["chat"]


def test_retag_reclaims_legacy_worker_rows(db, tmp_path):
    """Rows written before the tag existed are identified by workspace cwd.

    Two rows, not one: the count has to survive ``set_meta`` reusing the same
    cursor, which would otherwise report the meta write's rowcount instead.
    """
    workspaces = tmp_path / "kanban" / "workspaces"
    db.create_session(session_id="legacy", source="cli", cwd=str(workspaces / "t_b21733fb"))
    db.create_session(session_id="legacy2", source="cli", cwd=str(workspaces / "t_c0ffee"))
    db.create_session(session_id="mine", source="cli", cwd=str(tmp_path / "www" / "repo"))

    assert db.retag_kanban_worker_sessions(str(workspaces)) == 2

    sources = {row[0]: row[1] for row in db._conn.execute("SELECT id, source FROM sessions")}
    assert sources == {"legacy": "kanban", "legacy2": "kanban", "mine": "cli"}


def test_retag_runs_once_per_workspaces_root(db, tmp_path):
    """The state_meta gate keeps the retag off every subsequent spawn."""
    workspaces = tmp_path / "kanban" / "workspaces"
    db.create_session(session_id="legacy", source="cli", cwd=str(workspaces / "t_a"))
    db.retag_kanban_worker_sessions(str(workspaces))

    # A row that a *new* worker would never write as `cli`; if the gate leaked,
    # a later sweep would grab it too.
    db.create_session(session_id="later", source="cli", cwd=str(workspaces / "t_b"))

    assert db.retag_kanban_worker_sessions(str(workspaces)) == 0
    row = db._conn.execute("SELECT source FROM sessions WHERE id = 'later'").fetchone()
    assert row[0] == "cli"


def test_retag_gate_is_per_board(db, tmp_path):
    """A second board's workspaces root still gets its own sweep.

    The gate is keyed on the root, so reclaiming board A must not convince the
    dispatcher that board B's legacy rows were already handled.
    """
    board_a = tmp_path / "kanban" / "boards" / "a" / "workspaces"
    board_b = tmp_path / "kanban" / "boards" / "b" / "workspaces"
    db.create_session(session_id="a1", source="cli", cwd=str(board_a / "t_a"))
    db.create_session(session_id="b1", source="cli", cwd=str(board_b / "t_b"))

    assert db.retag_kanban_worker_sessions(str(board_a)) == 1
    assert db.retag_kanban_worker_sessions(str(board_b)) == 1


def test_retag_gate_is_stable_across_root_spellings(db, tmp_path):
    """One root, however spelled, closes one gate.

    The dispatcher hands over ``str(Path)``; a trailing separator (or, on
    Windows, ``as_posix()`` / another drive-letter case) must reclaim the same
    rows and must not re-arm the sweep for a later row.
    """
    workspaces = tmp_path / "kanban" / "workspaces"
    db.create_session(session_id="legacy", source="cli", cwd=str(workspaces / "t_a"))

    assert db.retag_kanban_worker_sessions(str(workspaces) + os.sep) == 1

    db.create_session(session_id="later", source="cli", cwd=str(workspaces / "t_b"))
    spellings = [str(workspaces), str(workspaces) + os.sep]
    if os.name == "nt":
        spellings += [workspaces.as_posix(), str(workspaces).swapcase()]
    for spelling in spellings:
        assert db.retag_kanban_worker_sessions(spelling) == 0, spelling
    row = db._conn.execute("SELECT source FROM sessions WHERE id = 'later'").fetchone()
    assert row[0] == "cli"


@pytest.mark.skipif(os.name != "nt", reason="separator and case folding are NTFS semantics")
def test_retag_matches_native_and_posix_cwd_spellings_on_windows(db, tmp_path):
    """Rows are ``os.getcwd()``-native (backslashes, whatever drive-letter case the
    process inherited) while the root arrives as a ``Path`` spelling; the
    persisted cwd grammar admits either separator, so every spelling is one tree.
    """
    workspaces = tmp_path / "kanban" / "workspaces"
    native = str(workspaces / "t_native")
    posix = (workspaces / "t_posix").as_posix()
    other_case = str(workspaces / "t_case").swapcase()
    db.create_session(session_id="native", source="cli", cwd=native)
    db.create_session(session_id="posix", source="cli", cwd=posix)
    db.create_session(session_id="case", source="cli", cwd=other_case)
    # A sibling whose name merely starts with the root's last component.
    db.create_session(session_id="sibling", source="cli", cwd=str(workspaces) + "-old\t_x")

    assert db.retag_kanban_worker_sessions(workspaces.as_posix()) == 3

    sources = {row[0]: row[1] for row in db._conn.execute("SELECT id, source FROM sessions")}
    assert sources == {"native": "kanban", "posix": "kanban", "case": "kanban", "sibling": "cli"}


def test_retag_refuses_a_filesystem_root(db, tmp_path):
    """A root that is the whole drive/filesystem would retag every cli row on the host."""
    db.create_session(session_id="mine", source="cli", cwd=str(tmp_path / "www" / "repo"))

    assert db.retag_kanban_worker_sessions(os.path.abspath(os.sep)) == 0
    assert db.retag_kanban_worker_sessions(os.sep) == 0
    row = db._conn.execute("SELECT source FROM sessions WHERE id = 'mine'").fetchone()
    assert row[0] == "cli"
    assert db._conn.execute("SELECT COUNT(*) FROM state_meta WHERE key LIKE 'kanban_worker_source_retagged:%'").fetchone()[0] == 0


def _sources(db_path):
    database = SessionDB(db_path=db_path)
    try:
        rows = database._conn.execute("SELECT id, source FROM sessions").fetchall()
        gate = database._conn.execute(
            "SELECT COUNT(*) FROM state_meta WHERE key LIKE 'kanban_worker_source_retagged:%'"
        ).fetchone()[0]
    finally:
        database.close()
    return {row[0]: row[1] for row in rows}, gate


@pytest.fixture()
def split_homes(tmp_path, monkeypatch):
    """A profile-mode layout: the dispatcher runs as ``<root>/profiles/main`` while the
    board (``kanban_home``) is shared at ``<root>`` -- the live gateway's shape."""
    import hermes_state
    from hermes_cli import kanban_db_dispatch as kbd

    root = tmp_path
    profile = root / "profiles" / "main"
    profile.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(profile))
    # The hermetic conftest re-points the default; follow it to this profile the
    # way production resolves it (``get_hermes_home() / "state.db"``).
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", profile / "state.db")
    monkeypatch.delenv("HERMES_KANBAN_HOME", raising=False)
    monkeypatch.setattr(kbd, "_retagged_workspace_roots", set())
    return root, profile


def test_retag_sweeps_the_shared_root_state_db_too(split_homes):
    """Workers that ran before the profile existed wrote their rows to the root's
    state.db (the board is shared across profiles); the profile-mode dispatcher
    must reclaim those as well, not only its own profile DB.
    """
    from hermes_cli import kanban_db_dispatch as kbd

    root, profile = split_homes
    workspaces = root / "kanban" / "workspaces"
    for home, sid in ((root, "root-legacy"), (profile, "profile-legacy")):
        database = SessionDB(db_path=home / "state.db")
        database.create_session(session_id=sid, source="cli", cwd=str(workspaces / "t_a"))
        database.create_session(session_id=sid + "-mine", source="cli", cwd=str(home / "repo"))
        database.close()

    kbd._retag_legacy_worker_sessions(str(workspaces))

    assert _sources(root / "state.db") == ({"root-legacy": "kanban", "root-legacy-mine": "cli"}, 1)
    assert _sources(profile / "state.db") == ({"profile-legacy": "kanban", "profile-legacy-mine": "cli"}, 1)
    assert str(workspaces) in kbd._retagged_workspace_roots


def test_retag_never_creates_the_root_state_db(split_homes):
    """A root without a state.db (fresh install, custom layout) is left alone."""
    from hermes_cli import kanban_db_dispatch as kbd

    root, profile = split_homes
    workspaces = root / "kanban" / "workspaces"
    SessionDB(db_path=profile / "state.db").close()

    kbd._retag_legacy_worker_sessions(str(workspaces))

    assert not (root / "state.db").exists()
    assert _sources(profile / "state.db")[1] == 1


def test_retag_opens_the_profile_db_once_when_it_is_the_root(tmp_path, monkeypatch):
    """Root mode (``HERMES_HOME`` is the root itself): one file, one sweep."""
    import hermes_state
    from hermes_cli import kanban_db_dispatch as kbd

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", tmp_path / "state.db")
    monkeypatch.delenv("HERMES_KANBAN_HOME", raising=False)
    monkeypatch.setattr(kbd, "_retagged_workspace_roots", set())
    SessionDB(db_path=tmp_path / "state.db").close()
    opened = []

    class _Counting(hermes_state.SessionDB):
        def __init__(self, *args, **kwargs):
            opened.append(kwargs.get("db_path"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(hermes_state, "SessionDB", _Counting)

    kbd._retag_legacy_worker_sessions(str(tmp_path / "kanban" / "workspaces"))

    assert opened == [None]
    assert _sources(tmp_path / "state.db")[1] == 1


def test_retag_failure_on_one_db_is_retried_next_spawn(split_homes, monkeypatch):
    """A busy/broken DB must not latch the in-process gate: the meta gate keeps a
    retry idempotent, so the next spawn tries again."""
    import hermes_state
    from hermes_cli import kanban_db_dispatch as kbd

    root, profile = split_homes
    workspaces = root / "kanban" / "workspaces"
    for home in (root, profile):
        SessionDB(db_path=home / "state.db").close()
    real = hermes_state.SessionDB

    class _RootBroken(real):
        def __init__(self, *args, **kwargs):
            if kwargs.get("db_path") is not None:
                raise sqlite3.OperationalError("database is locked")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(hermes_state, "SessionDB", _RootBroken)

    kbd._retag_legacy_worker_sessions(str(workspaces))

    assert str(workspaces) not in kbd._retagged_workspace_roots
    assert _sources(profile / "state.db")[1] == 1  # the healthy DB was still swept
    assert _sources(root / "state.db")[1] == 0
