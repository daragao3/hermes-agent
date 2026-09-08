"""A `state.db` that was never initialised as a SESSION store must read as
ABSENT, not as an error -- while a store that genuinely cannot be read still
reports.

`state.db` is a filename shared by two independent schema owners. `SessionDB`
creates the full session schema; `tools/async_delegation.py::_connect` opens
the SAME path and creates ONLY its own `async_delegations` table. Whichever
runs first in a profile decides what the file holds, so a profile that ran an
async delegation but never recorded a session ends up with a valid, non-empty
SQLite database that has no `sessions` table.

Measured on this box 2026-09-08: `~/.hermes/profiles/matcher/state.db` is
12,288 bytes, holds exactly one table (`async_delegations`, zero rows), passes
`db_path.exists()`, opens read-only in 1.0ms and then raises `no such table:
sessions` on every query. That put a permanent
`{"profile": "matcher", "error": "no such table: sessions"}` into every poll of
the sidebar aggregate, which 8ca1e62d64 surfaced as a desktop warning toast.

The guard is a SCHEMA probe, NOT a byte-length or header check, and that
distinction is the point of `test_zero_byte_and_populated_are_the_same_defect`:
the same file is 0 bytes between `sqlite3.connect()` and its first checkpoint
(under WAL the schema sits in the `-wal` until then), so a length test measures
when you looked rather than what the file is, and would miss this exact
instance at 12,288 bytes.

`test_an_unreadable_session_store_is_still_reported` is the counterweight. The
whole value of 8ca1e62d64 is that a profile whose store cannot be read stops
being silently dropped, so this fix must not buy quiet by re-swallowing that.
"""
import sqlite3

import pytest


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch, _isolate_hermes_home):
    from hermes_constants import get_hermes_home
    from hermes_cli import profiles

    default_home = get_hermes_home()
    profiles_root = default_home / "profiles"
    worker_home = profiles_root / "worker_beta"
    for home in (default_home, worker_home):
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(profiles, "_get_default_hermes_home", lambda: default_home)
    monkeypatch.setattr(profiles, "_get_profiles_root", lambda: profiles_root)
    return {"default": default_home, "worker_beta": worker_home}


@pytest.fixture
def client(monkeypatch, isolated_profiles):
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    import hermes_state
    from hermes_constants import get_hermes_home
    from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN

    monkeypatch.setattr(hermes_state, "DEFAULT_DB_PATH", get_hermes_home() / "state.db")
    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return c


def _seed(home, rows):
    from hermes_state import SessionDB

    db = SessionDB(db_path=home / "state.db")
    try:
        for sid, src in rows:
            db.create_session(session_id=sid, source=src)
            db.append_message(session_id=sid, role="user", content="hi")
    finally:
        db.close()


def _make_delegation_only_db(home):
    """Reproduce what tools/async_delegation.py::_connect leaves behind.

    Same three statements in the same order, so this stays a reproduction of
    the real writer rather than a hand-built fixture.
    """
    path = home / "state.db"
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS async_delegations ("
        "delegation_id TEXT PRIMARY KEY, origin_session TEXT NOT NULL, "
        "state TEXT NOT NULL, dispatched_at REAL NOT NULL, updated_at REAL NOT NULL)"
    )
    conn.commit()
    conn.close()
    return path


def _drop_sidecars(target):
    for suffix in ("-wal", "-shm"):
        leftover = target.with_name(target.name + suffix)
        if leftover.exists():
            leftover.unlink()


def _sidebar(client, scope="all"):
    resp = client.get(
        "/api/profiles/sessions/sidebar"
        f"?recents_profile={scope}&recents_limit=20"
        "&recents_exclude=cron,subagent,tool,telegram"
    )
    assert resp.status_code == 200
    return resp.json()


def _profiles_sessions(client):
    resp = client.get("/api/profiles/sessions?limit=20")
    assert resp.status_code == 200
    return resp.json()


class TestNonSessionStateDbReadsAsAbsent:
    def test_sidebar_does_not_report_a_delegation_only_store(
        self, client, isolated_profiles
    ):
        """THE LIVE CASE. worker_beta stands in for `matcher`."""
        _seed(isolated_profiles["default"], [("d-1", "desktop")])
        _make_delegation_only_db(isolated_profiles["worker_beta"])

        payload = _sidebar(client)

        assert payload.get("errors", []) == []
        # And the healthy profile is unaffected.
        assert payload["recents"]["total"] == 1
        assert payload["recents"]["all_profile_totals"].get("default") == 1
        # Absent, not zero: it is not a session store, so it gets no count row.
        assert "worker_beta" not in payload["recents"]["all_profile_totals"]

    def test_profiles_sessions_does_not_report_a_delegation_only_store(
        self, client, isolated_profiles
    ):
        """The twin loop. Both had the identical exists()-only guard."""
        _seed(isolated_profiles["default"], [("d-1", "desktop")])
        _make_delegation_only_db(isolated_profiles["worker_beta"])

        payload = _profiles_sessions(client)

        assert payload.get("errors", []) == []

    def test_zero_byte_and_populated_are_the_same_defect(
        self, client, isolated_profiles
    ):
        """Pins WHY the guard is a schema probe and not a length check.

        A bare sqlite3.connect() leaves a 0-byte file; after a checkpoint the
        same file is 12,288 bytes. Both must be handled, so neither a
        `st_size == 0` test nor a header sniff would do.
        """
        _seed(isolated_profiles["default"], [("d-1", "desktop")])
        target = isolated_profiles["worker_beta"] / "state.db"
        target.touch()
        assert target.stat().st_size == 0

        assert _sidebar(client).get("errors", []) == []

        # Now the checkpointed, non-empty form of the very same defect.
        target.unlink()
        _make_delegation_only_db(isolated_profiles["worker_beta"])
        assert target.stat().st_size > 0
        probe = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        try:
            names = {r[0] for r in probe.execute("SELECT name FROM sqlite_master")}
        finally:
            probe.close()
        assert "sessions" not in names
        assert "async_delegations" in names

        assert _sidebar(client).get("errors", []) == []


class TestRealReadFailuresStillSurface:
    def test_an_unreadable_session_store_is_still_reported(
        self, client, isolated_profiles
    ):
        """THE COUNTERWEIGHT to the tests above.

        A profile that IS a session store but whose file is corrupt must still
        reach the client's errors array -- that is the whole point of
        8ca1e62d64, and quieting it would be a regression dressed as a fix.
        """
        _seed(isolated_profiles["default"], [("d-1", "desktop")])
        _seed(isolated_profiles["worker_beta"], [("w-1", "desktop")])

        target = isolated_profiles["worker_beta"] / "state.db"
        _drop_sidecars(target)
        # Corrupt the pages after the header so the file still opens and
        # `sessions` is still named in sqlite_master.
        blob = bytearray(target.read_bytes())
        end = min(len(blob), 40960)
        blob[4096:end] = b"\xff" * (end - 4096)
        target.write_bytes(bytes(blob))

        payload = _sidebar(client)

        reported = {e["profile"] for e in payload.get("errors", [])}
        assert "worker_beta" in reported, (
            "a corrupt SESSION store must still be reported; only a file that "
            "was never a session store may read as absent"
        )

    def test_has_session_schema_raises_rather_than_lying_when_unreadable(
        self, tmp_path
    ):
        """Unit-level pin on the probe's own contract.

        has_session_schema() must not turn an I/O failure into False -- that
        would route every real breakage into the silent `continue`.
        """
        from hermes_state import SessionDB

        home = tmp_path / "broken"
        home.mkdir()
        _seed(home, [("s-1", "desktop")])
        target = home / "state.db"
        _drop_sidecars(target)

        db = SessionDB(db_path=target, read_only=True)
        try:
            assert db.has_session_schema() is True
        finally:
            db.close()

        # A valid header over a destroyed page 1: sqlite_master itself is
        # unreadable, which is exactly the class that must NOT read as False.
        target.write_bytes(b"SQLite format 3\x00" + b"\xff" * 8176)
        with pytest.raises(sqlite3.DatabaseError):
            db = SessionDB(db_path=target, read_only=True)
            try:
                db.has_session_schema()
            finally:
                db.close()

    def test_delegation_only_store_reads_as_false_not_an_error(self, tmp_path):
        """The other half of the probe's contract, at unit level."""
        from hermes_state import SessionDB

        home = tmp_path / "delegation"
        home.mkdir()
        target = _make_delegation_only_db(home)

        db = SessionDB(db_path=target, read_only=True)
        try:
            assert db.has_session_schema() is False
        finally:
            db.close()
